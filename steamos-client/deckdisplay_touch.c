// ==============================================================================
// DeckDisplay - Touchscreen Evdev to USB HID Digitizer Daemon for Steam Deck
// Captures raw input events from the internal touchscreen controller (FTS3528 /
// Goodix), applies native 90° portrait-to-landscape rotation for Steam Deck LCD
// and OLED displays, normalizes coordinates to 0..32767, and emits HID reports
// to /dev/hidg0.
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

// Поиск тачскрина Steam Deck (FTS3528 / контроллеры с INPUT_PROP_DIRECT)
static int find_touchscreen_device(int *min_x, int *max_x, int *min_y, int *max_y) {
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

        // Fallback на стандартные ABS_X/ABS_Y если MT не объявлены
        if (!has_x) {
            has_x = (ioctl(fd, EVIOCGABS(ABS_X), &abs_x) == 0 && abs_x.maximum > 0);
        }
        if (!has_y) {
            has_y = (ioctl(fd, EVIOCGABS(ABS_Y), &abs_y) == 0 && abs_y.maximum > 0);
        }

        // Определение тачскрина по имени (FTS / FocalTech / Goodix) или свойству DIRECT
        if (has_x && has_y && (strstr(name, "FTS") != NULL ||
                               strstr(name, "Goodix") != NULL ||
                               (propbits & (1UL << INPUT_PROP_DIRECT)))) {
            printf("[TouchDaemon] Обнаружен сенсорный экран: %s (%s)\n", name, path);
            printf("[TouchDaemon] Калибровочный диапазон: X:[%d..%d], Y:[%d..%d]\n",
                   abs_x.minimum, abs_x.maximum, abs_y.minimum, abs_y.maximum);

            *min_x = abs_x.minimum;
            *max_x = abs_x.maximum;
            *min_y = abs_y.minimum;
            *max_y = abs_y.maximum;
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
                        int min_x, int max_x, int min_y, int max_y, bool portrait_panel) {
    struct hid_touch_report rep = {0};

    // 0x03 = TipSwitch (Bit 0) + InRange (Bit 1) при касании
    // 0x00 = полное отпускание (предотвращает зависание курсора и фантомный ховер)
    rep.buttons = touching ? 0x03 : 0x00;
    rep.padding = 0x00;

    long span_x = (max_x - min_x) > 0 ? (max_x - min_x) : 800;
    long span_y = (max_y - min_y) > 0 ? (max_y - min_y) : 1280;

    if (portrait_panel) {
        // Физическая матрица Steam Deck (800x1280) повернута на 90 градусов:
        // Альбомный X = Raw Y
        // Альбомный Y = (Max_X - Raw X)
        long norm_x = ((long)(raw_y - min_y) * 32767L) / span_y;
        long norm_y = ((long)(max_x - raw_x) * 32767L) / span_x;
        rep.x = clamp_u16(norm_x);
        rep.y = clamp_u16(norm_y);
    } else {
        long norm_x = ((long)(raw_x - min_x) * 32767L) / span_x;
        long norm_y = ((long)(raw_y - min_y) * 32767L) / span_y;
        rep.x = clamp_u16(norm_x);
        rep.y = clamp_u16(norm_y);
    }

    ssize_t written = write(hid_fd, &rep, sizeof(rep));
    if (written < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
        // При ошибках записи (например, если хост временно отключил USB) не падаем
    }
}

int main(int argc, char **argv) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGHUP, handle_signal);

    const char *hid_path = (argc > 1) ? argv[1] : "/dev/hidg0";
    printf("[TouchDaemon] Запуск демона сенсорного ввода -> %s\n", hid_path);

    int hid_fd = open(hid_path, O_WRONLY | O_NONBLOCK);
    if (hid_fd < 0) {
        fprintf(stderr, "[TouchDaemon] Ошибка: Не удалось открыть %s: %s\n", hid_path, strerror(errno));
        fprintf(stderr, "[TouchDaemon] Убедитесь, что гаджет запущен (deckdisplay-gadget.sh)\n");
        return 1;
    }

    int min_x = 0, max_x = 800, min_y = 0, max_y = 1280;
    int ev_fd = find_touchscreen_device(&min_x, &max_x, &min_y, &max_y);
    if (ev_fd < 0) {
        fprintf(stderr, "[TouchDaemon] Ошибка: Устройство сенсорного экрана не найдено!\n");
        close(hid_fd);
        return 1;
    }

    // Если максимальный X меньше максимального Y (например, 800 < 1280), панель аппаратно портретная
    bool portrait_panel = (max_x < max_y);
    printf("[TouchDaemon] Тип ориентации: %s\n",
           portrait_panel ? "Портретная матрица (авто-ротация 90° в альбомный вид)" : "Нативная альбомная");

    int cur_x = min_x;
    int cur_y = min_y;
    int current_slot = 0;
    bool touching = false;
    bool dirty = false;

    struct pollfd pfd;
    pfd.fd = ev_fd;
    pfd.events = POLLIN;

    struct input_event ev;
    while (g_running) {
        // Использование poll() с таймаутом 100 мс:
        // Полностью исключает нагрузку на CPU (0.0% при простое) и сохраняет батарею Steam Deck!
        int ret = poll(&pfd, 1, 100);
        if (ret < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (ret == 0) {
            // Таймаут poll, проверяем флаг g_running
            continue;
        }

        if (pfd.revents & POLLIN) {
            while (true) {
                ssize_t n = read(ev_fd, &ev, sizeof(ev));
                if (n < (ssize_t)sizeof(ev)) {
                    break;
                }

                if (ev.type == EV_ABS) {
                    if (ev.code == ABS_MT_SLOT) {
                        current_slot = ev.value;
                    } else if (current_slot == 0) { // Отслеживаем основной контакт (Slot 0)
                        if (ev.code == ABS_MT_TRACKING_ID) {
                            touching = (ev.value >= 0);
                            dirty = true;
                        } else if (ev.code == ABS_MT_POSITION_X || ev.code == ABS_X) {
                            cur_x = ev.value;
                            dirty = true;
                        } else if (ev.code == ABS_MT_POSITION_Y || ev.code == ABS_Y) {
                            cur_y = ev.value;
                            dirty = true;
                        }
                    }
                } else if (ev.type == EV_KEY && ev.code == BTN_TOUCH) {
                    touching = (ev.value != 0);
                    dirty = true;
                } else if (ev.type == EV_SYN && ev.code == SYN_REPORT) {
                    if (dirty) {
                        send_report(hid_fd, touching, cur_x, cur_y, min_x, max_x, min_y, max_y, portrait_panel);
                        dirty = false;
                    }
                }
            }
        }
    }

    printf("[TouchDaemon] Завершение работы...\n");
    // Отправляем финальный репорт сброса касания
    send_report(hid_fd, false, cur_x, cur_y, min_x, max_x, min_y, max_y, portrait_panel);

    close(ev_fd);
    close(hid_fd);
    return 0;
}
