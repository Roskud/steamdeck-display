# ==============================================================================
# DeckDisplay - CMake Build Configuration for Windows Host Server
# Builds deckdisplay_server.exe using MSVC, Clang-CL, or MinGW
# ==============================================================================

cmake_minimum_required(VERSION 3.20)
project(DeckDisplayServer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Поиск FFmpeg (через vcpkg, gyan.dev или системные пути)
find_path(AVCODEC_INCLUDE_DIR NAMES libavcodec/avcodec.h
    PATHS
    "$ENV{FFMPEG_DIR}/include"
    "C:/vcpkg/installed/x64-windows/include"
    "C:/ffmpeg/include"
)

find_library(AVCODEC_LIBRARY NAMES avcodec
    PATHS
    "$ENV{FFMPEG_DIR}/lib"
    "C:/vcpkg/installed/x64-windows/lib"
    "C:/ffmpeg/lib"
)

find_library(AVUTIL_LIBRARY NAMES avutil
    PATHS
    "$ENV{FFMPEG_DIR}/lib"
    "C:/vcpkg/installed/x64-windows/lib"
    "C:/ffmpeg/lib"
)

add_executable(deckdisplay_server deckdisplay_server.cpp)

if(AVCODEC_INCLUDE_DIR)
    target_include_directories(deckdisplay_server PRIVATE ${AVCODEC_INCLUDE_DIR})
endif()

if(AVCODEC_LIBRARY AND AVUTIL_LIBRARY)
    target_link_libraries(deckdisplay_server PRIVATE
        ${AVCODEC_LIBRARY}
        ${AVUTIL_LIBRARY}
    )
else()
    message(STATUS "FFmpeg библиотеки не найдены по стандартным путям. При линковке проверьте VCPKG_TARGET_TRIPLET=x64-windows или FFMPEG_DIR.")
endif()

target_link_libraries(deckdisplay_server PRIVATE
    d3d11
    dxgi
    ws2_32
)

if(MSVC)
    target_compile_options(deckdisplay_server PRIVATE /W4 /O2 /permissive-)
endif()
