// ==============================================================================
// DeckDisplay - Decky Loader Quick Access Menu Interface (React / TypeScript)
// Provides UI in SteamOS Gaming Mode for display streaming control,
// touchscreen toggle, and hardware connection status monitoring.
// ==============================================================================

import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import {
  addEventListener,
  removeEventListener,
  callable,
  definePlugin,
  toaster,
} from "@decky/api";
import { useState, useEffect, FC } from "react";
import { FaDesktop, FaUsb, FaHandPointer, FaPlay, FaStop } from "react-icons/fa";

interface DeckDisplaySettings {
  udp_port: number;
  fps: number;
  touch_enabled: boolean;
  auto_plug_and_play: boolean;
  auto_enable_gadget_on_boot: boolean;
}

interface DeckDisplayStatus {
  gadget_active: boolean;
  udc_controller: string;
  usb_connected: boolean;
  client_running: boolean;
  touch_running: boolean;
  deck_ip: string;
  host_ip: string;
  binaries_installed: boolean;
  settings: DeckDisplaySettings;
}

// Привязка асинхронных RPC-вызовов к бэкенду main.py
const getStatus = callable<[], DeckDisplayStatus>("get_status");
const setGadgetEnabled = callable<[enabled: boolean], DeckDisplayStatus>("set_gadget_enabled");
const setStreamActive = callable<[active: boolean], DeckDisplayStatus>("set_stream_active");
const setTouchEnabled = callable<[enabled: boolean], DeckDisplayStatus>("set_touch_enabled");
const updateSettings = callable<[new_settings: Partial<DeckDisplaySettings>], DeckDisplayStatus>("update_settings");

const Content: FC = () => {
  const [status, setStatus] = useState<DeckDisplayStatus | null>(null);
  const [busy, setBusy] = useState<boolean>(false);

  useEffect(() => {
    getStatus().then(setStatus).catch(console.error);

    const listener = addEventListener<[DeckDisplayStatus]>("deckdisplay_status", (newStatus) => {
      setStatus(newStatus);
    });

    return () => {
      removeEventListener("deckdisplay_status", listener);
    };
  }, []);

  if (!status) {
    return (
      <PanelSection title="Статус системы">
        <PanelSectionRow>
          <Field label="Загрузка состояния DeckDisplay..." />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const handleGadgetToggle = async (val: boolean) => {
    setBusy(true);
    try {
      const updated = await setGadgetEnabled(val);
      setStatus(updated);
      toaster.toast({
        title: "DeckDisplay",
        body: val ? "USB-Гаджет (CDC-NCM + HID) активирован" : "USB-Гаджет отключен",
      });
    } finally {
      setBusy(false);
    }
  };

  const handleStreamToggle = async () => {
    setBusy(true);
    try {
      const targetState = !status.client_running;
      const updated = await setStreamActive(targetState);
      setStatus(updated);
    } finally {
      setBusy(false);
    }
  };

  const handleTouchToggle = async (val: boolean) => {
    const updated = await setTouchEnabled(val);
    setStatus(updated);
  };

  const handleSettingChange = async (patch: Partial<DeckDisplaySettings>) => {
    const updated = await updateSettings(patch);
    setStatus(updated);
  };

  const portOptions = [
    { data: 5000, label: "UDP 5000 (По умолчанию)" },
    { data: 5001, label: "UDP 5001 (Резервный)" },
    { data: 5555, label: "UDP 5555" },
  ];

  return (
    <div>
      {/* Секция 1: Управление и индикация статуса */}
      <PanelSection title="Управление монитором">
        <PanelSectionRow>
          <Field
            label="Статус подключения USB-C"
            description={
              status.usb_connected
                ? `ПК подключен (${status.host_ip} ⇄ ${status.deck_ip})`
                : status.gadget_active
                ? "Ожидание кабеля USB-C от ПК..."
                : "USB-Гаджет выключен"
            }
          >
            <span
              style={{
                color: status.usb_connected
                  ? "#4caf50"
                  : status.gadget_active
                  ? "#ff9800"
                  : "#9e9e9e",
                fontWeight: "bold",
              }}
            >
              {status.usb_connected ? "ONLINE" : status.gadget_active ? "READY" : "OFF"}
            </span>
          </Field>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy || !status.binaries_installed}
            onClick={handleStreamToggle}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "8px" }}>
              {status.client_running ? <FaStop color="#f44336" /> : <FaPlay color="#4caf50" />}
              <span>
                {status.client_running
                  ? "Остановить экран (Вернуться в Steam)"
                  : "Открыть экран ПК (Запустить клиент)"}
              </span>
            </div>
          </ButtonItem>
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Режим USB-Гаджета (NCM + HID)"
            description="Эмуляция сетевой карты 10 Гбит/с и тачскрина"
            icon={<FaUsb />}
            checked={status.gadget_active}
            disabled={busy}
            onChange={handleGadgetToggle}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Сенсорный ввод (Touchscreen)"
            description={status.touch_running ? "Активен (/dev/hidg0)" : "Отключен"}
            icon={<FaHandPointer />}
            checked={status.settings.touch_enabled}
            disabled={busy}
            onChange={handleTouchToggle}
          />
        </PanelSectionRow>
      </PanelSection>

      {/* Секция 2: Автоматизация Plug & Play */}
      <PanelSection title="Параметры Plug & Play">
        <PanelSectionRow>
          <ToggleField
            label="Автозапуск при подключении кабеля"
            description="Открывать экран при подключении USB-C и закрывать при отключении"
            checked={status.settings.auto_plug_and_play}
            onChange={(val) => handleSettingChange({ auto_plug_and_play: val })}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Активировать гаджет при старте SteamOS"
            description="Поднимать интерфейс usb0 сразу после включения консоли"
            checked={status.settings.auto_enable_gadget_on_boot}
            onChange={(val) => handleSettingChange({ auto_enable_gadget_on_boot: val })}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <DropdownItem
            label="Порт видеопотока"
            menuLabel="Выберите порт UDP"
            rgOptions={portOptions}
            selectedOption={status.settings.udp_port}
            onChange={(opt) => handleSettingChange({ udp_port: opt.data })}
          />
        </PanelSectionRow>
      </PanelSection>

      {/* Секция 3: Диагностика оборудования */}
      <PanelSection title="Диагностика оборудования">
        <PanelSectionRow>
          <Field label="Контроллер UDC" description={status.udc_controller} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field
            label="Бинарные модули C/C++"
            description={
              status.binaries_installed
                ? "Установлены в /home/deck/deckdisplay"
                : "Не найдены! Выполните make в steamos-client"
            }
          />
        </PanelSectionRow>
      </PanelSection>
    </div>
  );
};

export default definePlugin(() => {
  return {
    name: "DeckDisplay",
    titleView: <div className={staticClasses.Title}>DeckDisplay Monitor</div>,
    content: <Content />,
    icon: <FaDesktop />,
    onDismount() {},
  };
});
