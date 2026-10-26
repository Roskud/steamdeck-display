// ==============================================================================
// DeckDisplay - Touchscreen Evdev to USB HID Digitizer Daemon for Steam Deck
// Captures raw input events from the internal touchscreen controller (FTS3528 /
// Goodix), applies native 90° portrait-to-landscape rotation for Steam Deck LCD
// and OLED displays, normalizes coordinates to 0..32767, and emits HID reports
// to /dev/hidg0.
// Supports custom rotation degrees, inversion flags, and dynamic slot tracking.
// ==============================================================================

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <dirent.h>
#include <signal.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <linux/input.h>

#define MAX_SLOTS 16

static volatile sig_atomic_t g_running = 1;

static void handle_signal(int sig) {
    (void)sig;
    g_running = 0;
}

#pragma pack(push, 1)
struct hid_touch_report {
    uint8_t  buttons; // Bit 0: Tip Switch, Bit 1: In Range
    uint16_t x;       // 0..32767 (Little-Endian)
    uint16_t y;       // 0..32767 (Little-Endian)
    uint8_t  padding; // 0x00
};
#pragma pack(pop)

struct touch_config {
    const char *hid_path;
    const char *device_path;
    int  rotation;     // -1: auto, 0: 0 deg, 90: 90 deg, 180: 180 deg, 270: 270 deg
    bool invert_x;
    bool invert_y;
    bool swap_xy;
    bool verbose;
};

struct slot_state {
    bool active;
    int x;
    int y;
};

// Автоматический поиск устройства сенсорного экрана в /dev/input
static int find_touchscreen_device(int *min_x, int *max_x, int *min_y, int *max_y, char *out_path, size_t max_path_len) {
    DIR *dir = opendir("/dev/input");
    if (!dir) {
        perror("[TouchDaemon] Ошибка открытия /dev/input");
        return -1;
    }

    struct dirent *entry;
    int found_fd = -1;

    while ((entry = readdir(dir)) != NULL) {
        if (strncmp(entry->d_name, "event", 5) != 0) continue;

        char path[256];
        snprintf(path, sizeof(path), "/dev/input/%s", entry->d_name);

        int fd = open(path, O_RDONLY | O_NONBLOCK);
        if (fd < 0) continue;

        char name[256] = "Unknown";
        ioctl(fd, EVIOCGNAME(sizeof(name)), name);

        unsigned long propbits = 0;
        ioctl(fd, EVIOCGPROP(sizeof(propbits)), &propbits);

        struct input_absinfo abs_x = {0}, abs_y = {0};
        bool has_x = (ioctl(fd, EVIOCGABS(ABS_MT_POSITION_X), &abs_x) == 0 && abs_x.maximum > 0);
        bool has_y = (ioctl(fd, EVIOCGABS(ABS_MT_POSITION_Y), &abs_y) == 0 && abs_y.maximum > 0);

        if (!has_x) {
            has_x = (ioctl(fd, EVIOCGABS(ABS_X), &abs_x) == 0 && abs_x.maximum > 0);
        }
        if (!has_y) {
            has_y = (ioctl(fd, EVIOCGABS(ABS_Y), &abs_y) == 0 && abs_y.maximum > 0);
        }

        // Определение тачскрина по контроллеру FTS (FocalTech) / Goodix или свойству INPUT_PROP_DIRECT
        if (has_x && has_y && (strstr(name, "FTS") != NULL ||
                               strstr(name, "Goodix") != NULL ||
                               (propbits & (1UL << INPUT_PROP_DIRECT)))) {
            printf("[TouchDaemon] Обнаружен сенсорный экран: %s (%s)\n", name, path);
            printf("[TouchDaemon] Аппаратные границы: X:[%d..%d], Y:[%d..%d]\n",
                   abs_x.minimum, abs_x.maximum, abs_y.minimum, abs_y.maximum);

            *min_x = abs_x.minimum;
            *max_x = abs_x.maximum;
            *min_y = abs_y.minimum;
            *max_y = abs_y.maximum;
            if (out_path && max_path_len > 0) {
                strncpy(out_path, path, max_path_len - 1);
                out_path[max_path_len - 1] = '\0';
            }
            found_fd = fd;
            break;
        }
        close(fd);
    }

    closedir(dir);
    return found_fd;
}

static inline uint16_t clamp_u16(long val) {
    if (val < 0) return 0;
    if (val > 32767) return 32767;
    return (uint16_t)val;
}

static void send_report(int hid_fd, bool touching, int raw_x, int raw_y,
                        int min_x, int max_x, int min_y, int max_y, const struct touch_config *cfg) {
    struct hid_touch_report rep = {0};

    // 0x03 = TipSwitch (Bit 0) + InRange (Bit 1) при касании
    // 0x00 = полное отпускание (предотвращает залипание и ложный ховер на Windows)
    rep.buttons = touching ? 0x03 : 0x00;
    rep.padding = 0x00;

    long span_x = (max_x - min_x) > 0 ? (max_x - min_x) : 800;
    long span_y = (max_y - min_y) > 0 ? (max_y - min_y) : 1280;

    // Нормализация координат raw_x, raw_y в 0..32767
    long norm_x = 0;
    long norm_y = 0;

    // Вычисление ротации (по умолчанию для Steam Deck: 90° поворот физической портретной матрицы 800x1280)
    int rot = cfg->rotation;
    if (rot < 0) {
        // Режим автоопределения
        rot = (max_x < max_y) ? 90 : 0;
    }

    switch (rot) {
        case 90:
            // Steam Deck Native (Landscape X = Raw Y, Landscape Y = Max_X - Raw X)
            norm_x = ((long)(raw_y - min_y) * 32767L) / span_y;
            norm_y = ((long)(max_x - raw_x) * 32767L) / span_x;
            break;
        case 180:
            norm_x = ((long)(max_x - raw_x) * 32767L) / span_x;
            norm_y = ((long)(max_y - raw_y) * 32767L) / span_y;
            break;
        case 270:
            norm_x = ((long)(max_y - raw_y) * 32767L) / span_y;
            norm_y = ((long)(raw_x - min_x) * 32767L) / span_x;
            break;
        case 0:
        default:
            norm_x = ((long)(raw_x - min_x) * 32767L) / span_x;
            norm_y = ((long)(raw_y - min_y) * 32767L) / span_y;
            break;
    }

    // Ручные модификаторы инверсии осей
    if (cfg->invert_x) {
        norm_x = 32767L - norm_x;
    }
    if (cfg->invert_y) {
        norm_y = 32767L - norm_y;
    }
    if (cfg->swap_xy) {
        long tmp = norm_x;
        norm_x = norm_y;
        norm_y = tmp;
    }

    rep.x = clamp_u16(norm_x);
    rep.y = clamp_u16(norm_y);

    ssize_t written = write(hid_fd, &rep, sizeof(rep));
    if (written < 0 && cfg->verbose) {
        // Ошибка записи (например, USB временно отключен хостом)
        fprintf(stderr, "[TouchDaemon] write error: %s\n", strerror(errno));
    }
}

static void print_usage(const char *prog) {
    printf("Использование: %s [опции] [путь_к_hidg]\n", prog);
    printf("Опции:\n");
    printf("  -g, --hid <path>       Путь к HID-гаджету (по умолчанию: /dev/hidg0)\n");
    printf("  -d, --device <path>    Путь к устройству evdev (по умолчанию: автопоиск)\n");
    printf("  -r, --rotate <deg>     Поворот матрицы: 0, 90, 180, 270, auto (по умолчанию: auto)\n");
    printf("  -x, --invert-x         Инвертировать ось X\n");
    printf("  -y, --invert-y         Инвертировать ось Y\n");
    printf("  -s, --swap-xy          Поменять местами оси X и Y\n");
    printf("  -v, --verbose          Подробный вывод координат\n");
    printf("  -h, --help             Показать эту справку\n");
}

int main(int argc, char **argv) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGHUP, handle_signal);

    struct touch_config cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.hid_path = "/dev/hidg0";
    cfg.device_path = NULL;
    cfg.rotation = -1; // auto
    cfg.invert_x = false;
    cfg.invert_y = false;
    cfg.swap_xy = false;
    cfg.verbose = false;

    // Разбор аргументов командной строки
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        } else if ((strcmp(argv[i], "-g") == 0 || strcmp(argv[i], "--hid") == 0) && i + 1 < argc) {
            cfg.hid_path = argv[++i];
        } else if ((strcmp(argv[i], "-d") == 0 || strcmp(argv[i], "--device") == 0) && i + 1 < argc) {
            cfg.device_path = argv[++i];
        } else if ((strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--rotate") == 0) && i + 1 < argc) {
            const char *val = argv[++i];
            if (strcmp(val, "auto") == 0) cfg.rotation = -1;
            else cfg.rotation = atoi(val);
        } else if (strcmp(argv[i], "-x") == 0 || strcmp(argv[i], "--invert-x") == 0) {
            cfg.invert_x = true;
        } else if (strcmp(argv[i], "-y") == 0 || strcmp(argv[i], "--invert-y") == 0) {
            cfg.invert_y = true;
        } else if (strcmp(argv[i], "-s") == 0 || strcmp(argv[i], "--swap-xy") == 0) {
            cfg.swap_xy = true;
        } else if (strcmp(argv[i], "-v") == 0 || strcmp(argv[i], "--verbose") == 0) {
            cfg.verbose = true;
        } else if (argv[i][0] != '-') {
            cfg.hid_path = argv[i];
        }
    }

    printf("[TouchDaemon] Запуск демона сенсорного ввода -> %s\n", cfg.hid_path);

    int hid_fd = open(cfg.hid_path, O_WRONLY | O_NONBLOCK);
    if (hid_fd < 0) {
        fprintf(stderr, "[TouchDaemon] Ошибка: Не удалось открыть %s: %s\n", cfg.hid_path, strerror(errno));
        fprintf(stderr, "[TouchDaemon] Убедитесь, что гаджет запущен (deckdisplay-gadget.sh)\n");
        return 1;
    }

    int min_x = 0, max_x = 800, min_y = 0, max_y = 1280;
    int ev_fd = -1;
    char found_path[256] = "";

    if (cfg.device_path) {
        ev_fd = open(cfg.device_path, O_RDONLY | O_NONBLOCK);
        if (ev_fd >= 0) {
            struct input_absinfo abs_x = {0}, abs_y = {0};
            ioctl(ev_fd, EVIOCGABS(ABS_MT_POSITION_X), &abs_x);
            ioctl(ev_fd, EVIOCGABS(ABS_MT_POSITION_Y), &abs_y);
            min_x = abs_x.minimum; max_x = abs_x.maximum ? abs_x.maximum : 800;
            min_y = abs_y.minimum; max_y = abs_y.maximum ? abs_y.maximum : 1280;
            strncpy(found_path, cfg.device_path, sizeof(found_path) - 1);
        }
    } else {
        ev_fd = find_touchscreen_device(&min_x, &max_x, &min_y, &max_y, found_path, sizeof(found_path));
    }

    if (ev_fd < 0) {
        fprintf(stderr, "[TouchDaemon] Ошибка: Устройство сенсорного экрана не найдено!\n");
        close(hid_fd);
        return 1;
    }

    printf("[TouchDaemon] Отслеживание ввода: %s\n", found_path);
    int effective_rot = (cfg.rotation >= 0) ? cfg.rotation : ((max_x < max_y) ? 90 : 0);
    printf("[TouchDaemon] Режим ориентации: %d°%s%s%s\n",
           effective_rot,
           cfg.invert_x ? " [Invert-X]" : "",
           cfg.invert_y ? " [Invert-Y]" : "",
           cfg.swap_xy  ? " [Swap-XY]"  : "");

    struct slot_state slots[MAX_SLOTS];
    memset(slots, 0, sizeof(slots));

    int current_slot = 0;
    int active_slot = 0;
    bool touching = false;
    bool dirty = false;

    struct pollfd pfd;
    pfd.fd = ev_fd;
    pfd.events = POLLIN;

    struct input_event ev;
    while (g_running) {
        // poll() с таймаутом 100 мс гарантирует 0.0% CPU при отсутствии касаний
        int ret = poll(&pfd, 1, 100);
        if (ret < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (ret == 0) continue;

        if (pfd.revents & POLLIN) {
            while (true) {
                ssize_t n = read(ev_fd, &ev, sizeof(ev));
                if (n < (ssize_t)sizeof(ev)) break;

                if (ev.type == EV_ABS) {
                    if (ev.code == ABS_MT_SLOT) {
                        if (ev.value >= 0 && ev.value < MAX_SLOTS) {
                            current_slot = ev.value;
                        }
                    } else if (ev.code == ABS_MT_TRACKING_ID) {
                        if (current_slot >= 0 && current_slot < MAX_SLOTS) {
                            slots[current_slot].active = (ev.value >= 0);
                        }

                        // Обновляем active_slot: если текущий активный слот отпущен, переключаемся на любой другой активный
                        if (!slots[active_slot].active) {
                            bool found_other = false;
                            for (int s = 0; s < MAX_SLOTS; ++s) {
                                if (slots[s].active) {
                                    active_slot = s;
                                    found_other = true;
                                    break;
                                }
                            }
                            touching = found_other;
                        } else {
                            touching = true;
                        }
                        dirty = true;
                    } else if (ev.code == ABS_MT_POSITION_X || ev.code == ABS_X) {
                        if (current_slot >= 0 && current_slot < MAX_SLOTS) {
                            slots[current_slot].x = ev.value;
                            if (current_slot == active_slot) dirty = true;
                        }
                    } else if (ev.code == ABS_MT_POSITION_Y || ev.code == ABS_Y) {
                        if (current_slot >= 0 && current_slot < MAX_SLOTS) {
                            slots[current_slot].y = ev.value;
                            if (current_slot == active_slot) dirty = true;
                        }
                    }
                } else if (ev.type == EV_KEY && ev.code == BTN_TOUCH) {
                    touching = (ev.value != 0);
                    if (!touching) {
                        for (int s = 0; s < MAX_SLOTS; ++s) slots[s].active = false;
                    }
                    dirty = true;
                } else if (ev.type == EV_SYN && ev.code == SYN_REPORT) {
                    if (dirty) {
                        int cur_x = slots[active_slot].x;
                        int cur_y = slots[active_slot].y;
                        send_report(hid_fd, touching, cur_x, cur_y, min_x, max_x, min_y, max_y, &cfg);
                        dirty = false;
                    }
                }
            }
        }
    }

    printf("[TouchDaemon] Завершение работы...\n");
    // Отправляем финальный репорт сброса касания
    send_report(hid_fd, false, slots[active_slot].x, slots[active_slot].y, min_x, max_x, min_y, max_y, &cfg);

    close(ev_fd);
    close(hid_fd);
    return 0;
}
