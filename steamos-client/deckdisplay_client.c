// ==============================================================================
// DeckDisplay - Ultra Low-Latency Hardware Video Client for Steam Deck (SteamOS)
// Receives H.264 stream via UDP from Windows Host, decodes it via AMD RDNA2
// VA-API hardware video core (with CPU fallback), and renders to SDL2 window
// with direct scan-out support in gamescope.
// ==============================================================================

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
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

int main(int argc, char **argv) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    const char *url = (argc > 1)
        ? argv[1]
        : "udp://0.0.0.0:5000?fifo_size=65536&overrun_nonfatal=1&timeout=200000";

    printf("[Client] Инициализация видеоклиента DeckDisplay...\n");
    printf("[Client] Целевой адрес потока: %s\n", url);

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS) < 0) {
        fprintf(stderr, "[Client] Ошибка инициализации SDL: %s\n", SDL_GetError());
        return 1;
    }

    SDL_ShowCursor(SDL_DISABLE);

    // В игровом режиме gamescope окно 1280x800 переходит в режим Direct Scan-Out
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

    // Без VSync на уровне приложения для минимизации задержки вывода кадра
    SDL_Renderer *renderer = SDL_CreateRenderer(
        window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC
    );
    if (!renderer) {
        // Fallback на обычный акселерированный рендерер без флагов
        renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED);
    }
    if (!renderer) {
        fprintf(stderr, "[Client] Ошибка создания рендерера SDL: %s\n", SDL_GetError());
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 1;
    }

    SDL_Texture *texture = NULL;
    int tex_w = 0, tex_h = 0;

    AVFormatContext *input_ctx = avformat_alloc_context();
    if (!input_ctx) {
        fprintf(stderr, "[Client] Не удалось выделить память под AVFormatContext\n");
        SDL_DestroyRenderer(renderer);
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 1;
    }

    // Регистрация коллбэка прерывания для мгновенного выхода по сигналу/Escape
    input_ctx->interrupt_callback.callback = interrupt_callback;
    input_ctx->interrupt_callback.opaque = NULL;

    AVDictionary *opts = NULL;
    av_dict_set(&opts, "fflags", "nobuffer", 0);
    av_dict_set(&opts, "flags", "low_delay", 0);
    av_dict_set(&opts, "probesize", "32768", 0);
    av_dict_set(&opts, "analyzeduration", "0", 0);
    av_dict_set(&opts, "timeout", "200000", 0); // 200 мс таймаут на сокет для предотвращения блокировок

    printf("[Client] Ожидание подключения видеопотока...\n");

    const AVInputFormat *iformat = av_find_input_format("h264");
    if (avformat_open_input(&input_ctx, url, iformat, &opts) != 0) {
        // Попытка открыть с автоопределением контейнера
        if (avformat_open_input(&input_ctx, url, NULL, &opts) != 0) {
            fprintf(stderr, "[Client] Не удалось открыть входной поток: %s\n", url);
            av_dict_free(&opts);
            avformat_free_context(input_ctx);
            SDL_DestroyRenderer(renderer);
            SDL_DestroyWindow(window);
            SDL_Quit();
            return 1;
        }
    }
    av_dict_free(&opts);
    input_ctx->flags |= AVFMT_FLAG_NOBUFFER;

    const AVCodec *decoder = avcodec_find_decoder(AV_CODEC_ID_H264);
    if (!decoder) {
        fprintf(stderr, "[Client] Декодер H.264 не найден в FFmpeg!\n");
        avformat_close_input(&input_ctx);
        SDL_DestroyRenderer(renderer);
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 1;
    }

    AVCodecContext *codec_ctx = avcodec_alloc_context3(decoder);
    codec_ctx->flags |= AV_CODEC_FLAG_LOW_DELAY;
    codec_ctx->flags2 |= AV_CODEC_FLAG2_FAST;
    codec_ctx->thread_count = 2; // Минимальная многопоточность для низкой латентности

    // Попытка инициализации аппаратного ускорения VA-API на AMD Van Gogh APU
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
        fprintf(stderr, "[Client] Ошибка: Не удалось открыть контекст декодера H.264\n");
        avcodec_free_context(&codec_ctx);
        avformat_close_input(&input_ctx);
        if (g_hw_device_ctx) av_buffer_unref(&g_hw_device_ctx);
        SDL_DestroyRenderer(renderer);
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 1;
    }

    AVPacket *pkt = av_packet_alloc();
    AVFrame *frame = av_frame_alloc();
    AVFrame *sw_frame = av_frame_alloc();

    printf("[Client] Клиент готов! Нажмите Escape или кнопку питания для выхода.\n");

    SDL_Event event;
    while (g_running) {
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT ||
               (event.type == SDL_KEYDOWN && (event.key.keysym.sym == SDLK_ESCAPE ||
                                              event.key.keysym.sym == SDLK_q))) {
                g_running = 0;
            }
        }

        int read_res = av_read_frame(input_ctx, pkt);
        if (read_res >= 0) {
            if (avcodec_send_packet(codec_ctx, pkt) == 0) {
                while (avcodec_receive_frame(codec_ctx, frame) == 0) {
                    AVFrame *render_frame = frame;

                    // Если кадр в памяти GPU (VA-API), переносим его в системную память NV12
                    if (hw_accel_ok && frame->format == g_hw_pix_fmt) {
                        if (av_hwframe_transfer_data(sw_frame, frame, 0) >= 0) {
                            render_frame = sw_frame;
                        }
                    }

                    // Пересоздание текстуры при смене разрешения
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
                }
            }
            av_packet_unref(pkt);
        } else if (read_res == AVERROR(ETIMEDOUT) || read_res == AVERROR(EAGAIN)) {
            // Кратковременный таймаут UDP - продолжаем опрос SDL событий
            SDL_Delay(2);
        }
    }

    printf("[Client] Завершение работы клиента...\n");
    av_frame_free(&frame);
    av_frame_free(&sw_frame);
    av_packet_free(&pkt);
    avcodec_free_context(&codec_ctx);
    avformat_close_input(&input_ctx);
    if (g_hw_device_ctx) av_buffer_unref(&g_hw_device_ctx);
    if (texture) SDL_DestroyTexture(texture);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
