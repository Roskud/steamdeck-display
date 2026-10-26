// ==============================================================================
// DeckDisplay - High-Performance Windows Host Capture & Hardware Encoder Server
// Captures desktop directly from VRAM via DXGI Desktop Duplication API,
// transfers texture via Zero-Copy D3D11 to hardware encoder (NVENC / AMF / QSV),
// and streams low-latency H.264 NAL units over UDP to Steam Deck.
// ==============================================================================

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <wrl/client.h>

#include <iostream>
#include <string>
#include <vector>
#include <atomic>
#include <chrono>
#include <thread>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavutil/opt.h>
#include <libavutil/hwcontext.h>
#include <libavutil/hwcontext_d3d11va.h>
}

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "ws2_32.lib")

using Microsoft::WRL::ComPtr;

static std::atomic<bool> g_running(true);

BOOL WINAPI ConsoleCtrlHandler(DWORD dwCtrlType) {
    if (dwCtrlType == CTRL_C_EVENT || dwCtrlType == CTRL_CLOSE_EVENT || dwCtrlType == CTRL_BREAK_EVENT) {
        std::cout << "\n[Server] Получен сигнал завершения работы...\n";
        g_running = false;
        return TRUE;
    }
    return FALSE;
}

// Определение порядка опроса энкодеров на основе производителя видеокарты
std::vector<const char*> get_preferred_encoders(UINT vendorId) {
    std::vector<const char*> list;
    if (vendorId == 0x10DE) { // NVIDIA
        list = { "h264_nvenc", "h264_amf", "h264_qsv" };
    } else if (vendorId == 0x1002) { // AMD
        list = { "h264_amf", "h264_nvenc", "h264_qsv" };
    } else if (vendorId == 0x8086) { // Intel
        list = { "h264_qsv", "h264_nvenc", "h264_amf" };
    } else {
        list = { "h264_nvenc", "h264_amf", "h264_qsv" };
    }
    return list;
}

int main(int argc, char** argv) {
    SetConsoleCtrlHandler(ConsoleCtrlHandler, TRUE);

    // Разбор параметров командной строки
    std::string target_ip = (argc > 1) ? argv[1] : "10.77.77.2";
    int target_port       = (argc > 2) ? std::stoi(argv[2]) : 5000;
    int output_index      = (argc > 3) ? std::stoi(argv[3]) : 1;
    int target_fps        = (argc > 4) ? std::stoi(argv[4]) : 90;
    int bitrate           = (argc > 5) ? std::stoi(argv[5]) : 45000000; // 45 Мбит/с

    if (target_ip == "--help" || target_ip == "-h") {
        std::cout << "DeckDisplay Server - DXGI Zero-Copy Hardware Streamer\n"
                  << "Использование: deckdisplay_server.exe [IP] [Port] [OutputIndex] [FPS] [Bitrate]\n"
                  << "Параметры по умолчанию: 10.77.77.2 5000 1 90 45000000\n";
        return 0;
    }

    std::cout << "==================================================================\n";
    std::cout << "       DeckDisplay Windows Host Server (Zero-Copy DXGI + D3D11)   \n";
    std::cout << "==================================================================\n";
    std::cout << "[Server] Адрес назначения : " << target_ip << ":" << target_port << "\n";
    std::cout << "[Server] Индекс монитора  : #" << output_index << "\n";
    std::cout << "[Server] Частота кадров   : " << target_fps << " FPS\n";
    std::cout << "[Server] Битрейт видео    : " << (bitrate / 1000000) << " Mbps\n";

    // 1. Инициализация сетевого UDP-сокета с увеличенным буфером передачи
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        std::cerr << "[Server] Ошибка WSAStartup!\n";
        return 1;
    }

    SOCKET udp_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (udp_sock == INVALID_SOCKET) {
        std::cerr << "[Server] Ошибка создания сокета!\n";
        WSACleanup();
        return 1;
    }

    int sndbuf = 4 * 1024 * 1024; // 4 MB буфер передачи сокета для предотвращения потерь UDP
    setsockopt(udp_sock, SOL_SOCKET, SO_SNDBUF, reinterpret_cast<const char*>(&sndbuf), sizeof(sndbuf));

    sockaddr_in dest_addr{};
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(static_cast<u_short>(target_port));
    inet_pton(AF_INET, target_ip.c_str(), &dest_addr.sin_addr);

    // 2. Инициализация DirectX 11 устройства с поддержкой BGRA
    ComPtr<ID3D11Device> d3d_device;
    ComPtr<ID3D11DeviceContext> d3d_context;
    D3D_FEATURE_LEVEL feature_level;

    HRESULT hr = D3D11CreateDevice(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0,
        D3D11_SDK_VERSION, &d3d_device, &feature_level, &d3d_context
    );

    if (FAILED(hr)) {
        std::cerr << "[Server] Ошибка: D3D11CreateDevice завершился кодом 0x" << std::hex << hr << "\n";
        closesocket(udp_sock);
        WSACleanup();
        return 1;
    }

    ComPtr<IDXGIDevice> dxgi_device;
    d3d_device.As(&dxgi_device);
    ComPtr<IDXGIAdapter> dxgi_adapter;
    dxgi_device->GetAdapter(&dxgi_adapter);

    DXGI_ADAPTER_DESC adapter_desc{};
    dxgi_adapter->GetDesc(&adapter_desc);
    std::wcout << L"[Server] Аппаратный видеоадаптер: " << adapter_desc.Description << L"\n";

    // 3. Выбор монитора DXGI
    ComPtr<IDXGIOutput> dxgi_output;
    if (FAILED(dxgi_adapter->EnumOutputs(output_index, &dxgi_output))) {
        std::cout << "[Server] Монитор #" << output_index << " не найден! Переключение на монитор #0.\n";
        output_index = 0;
        if (FAILED(dxgi_adapter->EnumOutputs(0, &dxgi_output))) {
            std::cerr << "[Server] Ошибка: Не удалось обнаружить ни одного монитора DXGI!\n";
            closesocket(udp_sock);
            WSACleanup();
            return 1;
        }
    }

    DXGI_OUTPUT_DESC out_desc{};
    dxgi_output->GetDesc(&out_desc);
    int width  = out_desc.DesktopCoordinates.right - out_desc.DesktopCoordinates.left;
    int height = out_desc.DesktopCoordinates.bottom - out_desc.DesktopCoordinates.top;
    std::wcout << L"[Server] Захват дисплея [" << out_desc.DeviceName << L"]: "
               << width << L"x" << height << L" @ " << target_fps << L" Hz\n";

    ComPtr<IDXGIOutput1> dxgi_output1;
    dxgi_output.As(&dxgi_output1);
    ComPtr<IDXGIOutputDuplication> desk_dupl;
    hr = dxgi_output1->DuplicateOutput(d3d_device.Get(), &desk_dupl);
    if (FAILED(hr)) {
        std::cerr << "[Server] Ошибка DuplicateOutput (0x" << std::hex << hr << ")!\n";
        std::cerr << "[Server] Проверьте, что приложение не запущено под учетной записью с ограниченными правами.\n";
        closesocket(udp_sock);
        WSACleanup();
        return 1;
    }

    // 4. Настройка аппаратного энкодера FFmpeg с D3D11VA
    auto preferred_encoders = get_preferred_encoders(adapter_desc.VendorId);
    const AVCodec* encoder = nullptr;
    std::string chosen_encoder_name = "";

    for (const char* enc_name : preferred_encoders) {
        const AVCodec* c = avcodec_find_encoder_by_name(enc_name);
        if (c) {
            encoder = c;
            chosen_encoder_name = enc_name;
            std::cout << "[Server] Попытка активации энкодера: " << enc_name << "\n";
            break;
        }
    }

    if (!encoder) {
        encoder = avcodec_find_encoder_by_name("libx264");
        chosen_encoder_name = "libx264";
        std::cout << "[Server] Аппаратные энкодеры не найдены, fallback на libx264.\n";
    }

    if (!encoder) {
        std::cerr << "[Server] Ни один поддерживаемый энкодер H.264 не найден!\n";
        closesocket(udp_sock);
        WSACleanup();
        return 1;
    }

    AVCodecContext* enc_ctx = avcodec_alloc_context3(encoder);
    enc_ctx->width     = width;
    enc_ctx->height    = height;
    enc_ctx->time_base = { 1, target_fps };
    enc_ctx->framerate = { target_fps, 1 };
    enc_ctx->pix_fmt   = AV_PIX_FMT_D3D11;
    enc_ctx->bit_rate  = bitrate;
    enc_ctx->rc_max_rate = bitrate;
    enc_ctx->rc_buffer_size = bitrate / target_fps; // Однокадровый VBV буфер для сверхнизкой латентности
    // ВАЖНО: GOP size равен частоте кадров (1 IDR раз в секунду), чтобы при подключении
    // клиента или потере UDP пакета поток мгновенно восстанавливался в течение 1 сек!
    enc_ctx->gop_size  = target_fps;
    enc_ctx->max_b_frames = 0;
    enc_ctx->flags |= AV_CODEC_FLAG_LOW_DELAY;

    // Включение вставки SPS/PPS параметров в каждый IDR кадр
    av_opt_set(enc_ctx->priv_data, "preset", "p1", 0);
    av_opt_set(enc_ctx->priv_data, "tune", "ull", 0);
    av_opt_set(enc_ctx->priv_data, "zerolatency", "1", 0);
    av_opt_set(enc_ctx->priv_data, "repeat-headers", "1", 0);
    av_opt_set(enc_ctx->priv_data, "forced-idr", "1", 0);
    av_opt_set(enc_ctx->priv_data, "usage", "ultralowlatency", 0);       // Для AMD AMF
    av_opt_set(enc_ctx->priv_data, "header_insertion_mode", "idr", 0);  // Для AMD AMF

    // Инициализация аппаратного контекста D3D11VA
    AVBufferRef* hw_device_ref = av_hwdevice_ctx_alloc(AV_HWDEVICE_TYPE_D3D11VA);
    auto* device_ctx = reinterpret_cast<AVHWDeviceContext*>(hw_device_ref->data);
    auto* d3d11_hwctx = static_cast<AVD3D11VADeviceContext*>(device_ctx->hwctx);
    d3d11_hwctx->device = d3d_device.Get();
    d3d11_hwctx->device->AddRef();
    d3d11_hwctx->device_context = d3d_context.Get();
    d3d11_hwctx->device_context->AddRef();
    av_hwdevice_ctx_init(hw_device_ref);

    AVBufferRef* hw_frames_ref = av_hwframe_ctx_alloc(hw_device_ref);
    auto* frames_ctx = reinterpret_cast<AVHWFramesContext*>(hw_frames_ref->data);
    frames_ctx->format    = AV_PIX_FMT_D3D11;
    frames_ctx->sw_format = AV_PIX_FMT_BGRA;
    frames_ctx->width     = width;
    frames_ctx->height    = height;
    frames_ctx->initial_pool_size = 4;
    av_hwframe_ctx_init(hw_frames_ref);

    enc_ctx->hw_frames_ctx = av_buffer_ref(hw_frames_ref);

    if (avcodec_open2(enc_ctx, encoder, nullptr) < 0) {
        std::cerr << "[Server] Не удалось запустить энкодер " << chosen_encoder_name << "!\n";
        av_buffer_unref(&hw_frames_ref);
        av_buffer_unref(&hw_device_ref);
        avcodec_free_context(&enc_ctx);
        closesocket(udp_sock);
        WSACleanup();
        return 1;
    }

    std::cout << "[Server] Энкодер " << chosen_encoder_name << " успешно инициализирован.\n";
    std::cout << "[Server] Поток транслируется -> " << target_ip << ":" << target_port << "\n";
    std::cout << "[Server] Для остановки нажмите Ctrl+C.\n";

    AVFrame* hw_frame = av_frame_alloc();
    AVPacket* pkt = av_packet_alloc();
    int64_t pts = 0;

    // 5. Главный конвейер Zero-Copy захвата и стриминга
    while (g_running) {
        ComPtr<IDXGIResource> desk_resource;
        DXGI_OUTDUPL_FRAME_INFO frame_info;

        hr = desk_dupl->AcquireNextFrame(16, &frame_info, &desk_resource);
        if (hr == DXGI_ERROR_WAIT_TIMEOUT) {
            continue;
        }

        if (hr == DXGI_ERROR_ACCESS_LOST) {
            std::cout << "[Server] Внимание: Доступ к экрану временно потерян (смена разрешения/UAC). Переподключение...\n";
            desk_dupl.Reset();
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            dxgi_output1->DuplicateOutput(d3d_device.Get(), &desk_dupl);
            continue;
        }

        if (FAILED(hr)) {
            break;
        }

        ComPtr<ID3D11Texture2D> acquired_tex;
        desk_resource.As(&acquired_tex);

        if (av_hwframe_get_buffer(hw_frames_ref, hw_frame, 0) == 0) {
            auto* dst_tex = reinterpret_cast<ID3D11Texture2D*>(hw_frame->data[0]);
            int dst_index = static_cast<int>(reinterpret_cast<intptr_t>(hw_frame->data[1]));

            // Прямое аппаратное копирование текстуры внутри видеопамяти GPU (Zero-Copy)
            d3d_context->CopySubresourceRegion(dst_tex, dst_index, 0, 0, 0, acquired_tex.Get(), 0, nullptr);
            desk_dupl->ReleaseFrame();

            hw_frame->pts = pts++;
            if (avcodec_send_frame(enc_ctx, hw_frame) == 0) {
                while (avcodec_receive_packet(enc_ctx, pkt) == 0) {
                    // Фрагментация NAL-пакетов под MTU Ethernet (до 1400 байт) для предотвращения фрагментации IP
                    const uint8_t* data = pkt->data;
                    int remaining = pkt->size;
                    while (remaining > 0 && g_running) {
                        int chunk = (remaining > 1400) ? 1400 : remaining;
                        sendto(udp_sock, reinterpret_cast<const char*>(data), chunk, 0,
                               reinterpret_cast<sockaddr*>(&dest_addr), sizeof(dest_addr));
                        data += chunk;
                        remaining -= chunk;
                    }
                    av_packet_unref(pkt);
                }
            }
            av_frame_unref(hw_frame);
        } else {
            desk_dupl->ReleaseFrame();
        }
    }

    std::cout << "[Server] Очистка и освобождение ресурсов...\n";
    av_packet_free(&pkt);
    av_frame_free(&hw_frame);
    avcodec_free_context(&enc_ctx);
    av_buffer_unref(&hw_frames_ref);
    av_buffer_unref(&hw_device_ref);
    closesocket(udp_sock);
    WSACleanup();
    std::cout << "[Server] Сервер остановлен.\n";
    return 0;
}
