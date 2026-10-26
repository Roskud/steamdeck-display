// ==============================================================================
// DeckDisplay - Ultra Low-Latency Hardware Video Client for Steam Deck (SteamOS)
// Receives H.264 stream via UDP from Windows Host, decodes it via AMD RDNA2
// VA-API hardware video core (with CPU fallback), and renders to SDL2 window
// with direct scan-out support in gamescope.
// Supports continuous connection retry, auto-reconnect, and zero frame-buffering.
// ==============================================================================

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <signal.h>
#include <SDL2/SDL.h>
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
#include <libavutil/imgutils.h>
#include <libavutil/opt.h>

static volatile sig_atomic_t g_running = 1;
static AVBufferRef *g_hw_device_ctx = NULL;
static enum AVPixelFormat g_hw_pix_fmt = AV_PIX_FMT_NONE;

static void handle_signal(int sig) {
    (void)sig;
    g_running = 0;
}

static enum AVPixelFormat get_hw_format(AVCodecContext *ctx, const enum AVPixelFormat *pix_fmts) {
    (void)ctx;
    for (const enum AVPixelFormat *p = pix_fmts; *p != -1; p++) {
        if (*p == g_hw_pix_fmt) {
            return *p;
        }
    }
    fprintf(stderr, "[Client] Аппаратный формат VA-API не согласован, откат на софтверный декодер.\n");
    return AV_PIX_FMT_YUV420P;
}

static int interrupt_callback(void *opaque) {
    (void)opaque;
    return !g_running;
}

// Отрисовка экрана ожидания подключения в стилистике SteamOS (темно-синий градиент и карточка)
static void draw_waiting_screen(SDL_Renderer *renderer, int width, int height, int pulse) {
    // Темный фон SteamOS (#0d131b)
    SDL_SetRenderDrawColor(renderer, 13, 19, 27, 255);
    SDL_RenderClear(renderer);

    // Центрированная информационная панель
    int card_w = 560;
    int card_h = 200;
    int card_x = (width - card_w) / 2;
    int card_y = (height - card_h) / 2;

    SDL_Rect card_rect = { card_x, card_y, card_w, card_h };
    SDL_SetRenderDrawColor(renderer, 24, 34, 48, 255);
    SDL_RenderFillRect(renderer, &card_rect);

    // Цветная рамка панели (Steam Blue #1a9fff с мягкой пульсацией)
    int alpha = 180 + (pulse % 75);
    SDL_SetRenderDrawColor(renderer, 26, 159, 255, (Uint8)alpha);
    SDL_RenderDrawRect(renderer, &card_rect);

    // Внутренняя акцентная полоса состояния
    SDL_Rect bar_rect = { card_x + 30, card_y + 140, card_w - 60, 8 };
    SDL_SetRenderDrawColor(renderer, 35, 48, 66, 255);
    SDL_RenderFillRect(renderer, &bar_rect);

    int progress_w = ((pulse * 4) % (card_w - 60));
    SDL_Rect prog_rect = { card_x + 30, card_y + 140, progress_w, 8 };
    SDL_SetRenderDrawColor(renderer, 26, 159, 255, 255);
    SDL_RenderFillRect(renderer, &prog_rect);

    SDL_RenderPresent(renderer);
}

int main(int argc, char **argv) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGHUP, handle_signal);

    const char *url = (argc > 1)
        ? argv[1]
        : "udp://0.0.0.0:5000?fifo_size=65536&overrun_nonfatal=1";

    printf("====================================================================\n");
    printf("   DeckDisplay Client - Аппаратный видеодекодер для Steam Deck     \n");
    printf("====================================================================\n");
    printf("[Client] Адрес прослушивания : %s\n", url);
    printf("[Client] Нажмите Escape или 'Q' в любой момент для выхода.\n");

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS) < 0) {
        fprintf(stderr, "[Client] Ошибка инициализации SDL: %s\n", SDL_GetError());
        return 1;
    }

    SDL_ShowCursor(SDL_DISABLE);

    // Создание полноэкранного окна 1280x800 для прямого вывода в gamescope (Direct Scan-Out)
    SDL_Window *window = SDL_CreateWindow(
        "DeckDisplay Client",
        SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED,
        1280, 800,
        SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_BORDERLESS | SDL_WINDOW_ALLOW_HIGHDPI
    );

    if (!window) {
        fprintf(stderr, "[Client] Ошибка создания окна SDL: %s\n", SDL_GetError());
        SDL_Quit();
        return 1;
    }

    SDL_Renderer *renderer = SDL_CreateRenderer(
        window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC
    );
    if (!renderer) {
        renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED);
    }
    if (!renderer) {
        fprintf(stderr, "[Client] Ошибка создания рендерера SDL: %s\n", SDL_GetError());
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 1;
    }

    int win_w = 1280, win_h = 800;
    SDL_GetWindowSize(window, &win_w, &win_h);

    int pulse = 0;
    SDL_Event event;

    // Внешний цикл: непрерывное поддержание подключения и авто-восстановление при обрыве
    while (g_running) {
        // Опрос событий ввода SDL
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT ||
               (event.type == SDL_KEYDOWN && (event.key.keysym.sym == SDLK_ESCAPE ||
                                              event.key.keysym.sym == SDLK_q))) {
                g_running = 0;
                break;
            }
        }
        if (!g_running) break;

        draw_waiting_screen(renderer, win_w, win_h, pulse++);

        // Настройка параметров подключения к UDP-потоку H.264
        AVDictionary *opts = NULL;
        av_dict_set(&opts, "fflags", "nobuffer", 0);
        av_dict_set(&opts, "flags", "low_delay", 0);
        av_dict_set(&opts, "probesize", "32768", 0);
        av_dict_set(&opts, "analyzeduration", "0", 0);
        // Таймаут опроса сокета 500 мс на попытку (позволяет реагировать на Escape)
        av_dict_set(&opts, "timeout", "500000", 0);

        AVFormatContext *input_ctx = avformat_alloc_context();
        if (!input_ctx) {
            av_dict_free(&opts);
            SDL_Delay(100);
            continue;
        }

        input_ctx->interrupt_callback.callback = interrupt_callback;
        input_ctx->interrupt_callback.opaque = NULL;

        const AVInputFormat *iformat = av_find_input_format("h264");
        int ret = avformat_open_input(&input_ctx, url, iformat, &opts);
        av_dict_free(&opts);

        if (ret != 0) {
            // Видеопоток еще не пошел от ПК - ждем следующей итерации без завершения программы
            if (input_ctx) {
                avformat_close_input(&input_ctx);
            }
            SDL_Delay(50);
            continue;
        }

        input_ctx->flags |= AVFMT_FLAG_NOBUFFER;
        printf("[Client] Видеопоток обнаружен! Инициализация декодера...\n");

        const AVCodec *decoder = avcodec_find_decoder(AV_CODEC_ID_H264);
        if (!decoder) {
            fprintf(stderr, "[Client] Ошибка: Декодер H.264 не найден в FFmpeg!\n");
            avformat_close_input(&input_ctx);
            SDL_Delay(1000);
            continue;
        }

        AVCodecContext *codec_ctx = avcodec_alloc_context3(decoder);
        codec_ctx->flags |= AV_CODEC_FLAG_LOW_DELAY;
        codec_ctx->flags2 |= AV_CODEC_FLAG2_FAST;
        // ВАЖНО: thread_count = 1 или thread_type = SLICE исключает задержку кадровой очереди FFmpeg!
        codec_ctx->thread_count = 1;
        codec_ctx->thread_type = FF_THREAD_SLICE;

        // Попытка инициализации аппаратного ускорения VA-API на AMD Van Gogh (RDNA2)
        bool hw_accel_ok = false;
        if (av_hwdevice_ctx_create(&g_hw_device_ctx, AV_HWDEVICE_TYPE_VAAPI, "/dev/dri/renderD128", NULL, 0) >= 0 ||
            av_hwdevice_ctx_create(&g_hw_device_ctx, AV_HWDEVICE_TYPE_VAAPI, NULL, NULL, 0) >= 0) {
            g_hw_pix_fmt = AV_PIX_FMT_VAAPI;
            codec_ctx->hw_device_ctx = av_buffer_ref(g_hw_device_ctx);
            codec_ctx->get_format = get_hw_format;
            hw_accel_ok = true;
            printf("[Client] Аппаратный декодер VA-API (AMD RDNA2) успешно подключен!\n");
        } else {
            printf("[Client] Внимание: VA-API недоступен, переключение на софтверный декодер CPU.\n");
        }

        if (avcodec_open2(codec_ctx, decoder, NULL) < 0) {
            fprintf(stderr, "[Client] Не удалось открыть контекст декодера H.264\n");
            avcodec_free_context(&codec_ctx);
            avformat_close_input(&input_ctx);
            if (g_hw_device_ctx) av_buffer_unref(&g_hw_device_ctx);
            SDL_Delay(500);
            continue;
        }

        AVPacket *pkt = av_packet_alloc();
        AVFrame *frame = av_frame_alloc();
        AVFrame *sw_frame = av_frame_alloc();
        SDL_Texture *texture = NULL;
        int tex_w = 0, tex_h = 0;

        printf("[Client] Поток активен! Рендеринг запущен.\n");

        // Внутренний цикл: декодирование и отрисовка кадров активного потока
        while (g_running) {
            while (SDL_PollEvent(&event)) {
                if (event.type == SDL_QUIT ||
                   (event.type == SDL_KEYDOWN && (event.key.keysym.sym == SDLK_ESCAPE ||
                                                  event.key.keysym.sym == SDLK_q))) {
                    g_running = 0;
                    break;
                }
            }
            if (!g_running) break;

            int read_res = av_read_frame(input_ctx, pkt);
            if (read_res >= 0) {
                if (avcodec_send_packet(codec_ctx, pkt) == 0) {
                    while (avcodec_receive_frame(codec_ctx, frame) == 0) {
                        AVFrame *render_frame = frame;

                        // Перенос текстуры из GPU памяти VA-API в системную память NV12
                        if (hw_accel_ok && frame->format == g_hw_pix_fmt) {
                            if (av_hwframe_transfer_data(sw_frame, frame, 0) >= 0) {
                                render_frame = sw_frame;
                            }
                        }

                        // Пересоздание текстуры SDL при первом кадре или смене разрешения
                        if (!texture || tex_w != render_frame->width || tex_h != render_frame->height) {
                            if (texture) SDL_DestroyTexture(texture);
                            tex_w = render_frame->width;
                            tex_h = render_frame->height;
                            Uint32 sdl_fmt = (render_frame->format == AV_PIX_FMT_NV12)
                                             ? SDL_PIXELFORMAT_NV12
                                             : SDL_PIXELFORMAT_IYUV;
                            texture = SDL_CreateTexture(
                                renderer, sdl_fmt, SDL_TEXTUREACCESS_STREAMING, tex_w, tex_h
                            );
                            printf("[Client] Видеопоток синхронизирован: %dx%d (формат: %s)\n",
                                   tex_w, tex_h, (sdl_fmt == SDL_PIXELFORMAT_NV12) ? "NV12" : "IYUV");
                        }

                        if (texture) {
                            if (render_frame->format == AV_PIX_FMT_NV12) {
                                SDL_UpdateNVTexture(texture, NULL,
                                                    render_frame->data[0], render_frame->linesize[0],
                                                    render_frame->data[1], render_frame->linesize[1]);
                            } else {
                                SDL_UpdateYUVTexture(texture, NULL,
                                                     render_frame->data[0], render_frame->linesize[0],
                                                     render_frame->data[1], render_frame->linesize[1],
                                                     render_frame->data[2], render_frame->linesize[2]);
                            }

                            SDL_RenderClear(renderer);
                            SDL_RenderCopy(renderer, texture, NULL, NULL);
                            SDL_RenderPresent(renderer);
                        }

                        // Критично: освобождаем буферы sw_frame и frame после каждого кадра,
                        // чтобы предотвратить утечки памяти и ошибки EINVAL при смене разрешения!
                        av_frame_unref(sw_frame);
                        av_frame_unref(frame);
                    }
                }
                av_packet_unref(pkt);
            } else if (read_res == AVERROR(ETIMEDOUT) || read_res == AVERROR(EAGAIN)) {
                // Кратковременный таймаут сокета - продолжаем опрос событий
                SDL_Delay(1);
            } else {
                // Поток разорван (хост отключил стрим или выдернут кабель)
                printf("[Client] Поток приостановлен или отключен хостом. Переход в режим ожидания...\n");
                break;
            }
        }

        // Очистка ресурсов текущей сессии потока
        if (texture) SDL_DestroyTexture(texture);
        av_frame_free(&sw_frame);
        av_frame_free(&frame);
        av_packet_free(&pkt);
        avcodec_free_context(&codec_ctx);
        avformat_close_input(&input_ctx);
        if (g_hw_device_ctx) {
            av_buffer_unref(&g_hw_device_ctx);
            g_hw_device_ctx = NULL;
        }
    }

    printf("[Client] Завершение работы клиента DeckDisplay...\n");
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
