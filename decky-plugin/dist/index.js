// ==============================================================================
// DeckDisplay - Compiled Bundle for Decky Loader (dist/index.js)
// Pre-bundled IIFE distribution for immediate deployment into Decky Loader.
// ==============================================================================

(function (SP_REACT, DFL, DECKY_API) {
  'use strict';

  var React = SP_REACT;
  var useState = React.useState;
  var useEffect = React.useEffect;

  var ButtonItem = DFL.ButtonItem;
  var DropdownItem = DFL.DropdownItem;
  var Field = DFL.Field;
  var PanelSection = DFL.PanelSection;
  var PanelSectionRow = DFL.PanelSectionRow;
  var ToggleField = DFL.ToggleField;
  var staticClasses = DFL.staticClasses || {};

  var addEventListener = DECKY_API.addEventListener;
  var removeEventListener = DECKY_API.removeEventListener;
  var callable = DECKY_API.callable;
  var definePlugin = DECKY_API.definePlugin;
  var toaster = DECKY_API.toaster;

  // RPC-функции бэкенда main.py
  var getStatus = callable("get_status");
  var setGadgetEnabled = callable("set_gadget_enabled");
  var setStreamActive = callable("set_stream_active");
  var setTouchEnabled = callable("set_touch_enabled");
  var updateSettings = callable("update_settings");

  // Векторные SVG иконки
  function IconDesktop() {
    return React.createElement('svg', {
      stroke: 'currentColor', fill: 'currentColor', strokeWidth: '0', viewBox: '0 0 576 512',
      height: '1em', width: '1em', style: { display: 'inline-block', verticalAlign: 'middle' }
    }, React.createElement('path', {
      d: 'M528 0H48C21.5 0 0 21.5 0 48v320c0 26.5 21.5 48 48 48h192l-16 48h-72c-13.3 0-24 10.7-24 24s10.7 24 24 24h272c13.3 0 24-10.7 24-24s-10.7-24-24-24h-72l-16-48h192c26.5 0 48-21.5 48-48V48c0-26.5-21.5-48-48-48zm0 352H48V48h480v304z'
    }));
  }

  function IconUsb() {
    return React.createElement('svg', {
      stroke: 'currentColor', fill: 'currentColor', strokeWidth: '0', viewBox: '0 0 448 512',
      height: '1em', width: '1em', style: { display: 'inline-block', verticalAlign: 'middle' }
    }, React.createElement('path', {
      d: 'M448 96c0-35.3-28.7-64-64-64H64C28.7 32 0 60.7 0 96v320c0 35.3 28.7 64 64 64h320c35.3 0 64-28.7 64-64V96zM176 80h96v32h-96V80zm160 304c0 8.8-7.2 16-16 16H128c-8.8 0-16-7.2-16-16V224h224v160z'
    }));
  }

  function IconTouch() {
    return React.createElement('svg', {
      stroke: 'currentColor', fill: 'currentColor', strokeWidth: '0', viewBox: '0 0 448 512',
      height: '1em', width: '1em', style: { display: 'inline-block', verticalAlign: 'middle' }
    }, React.createElement('path', {
      d: 'M9.4 233.4c-12.5 12.5-12.5 32.8 0 45.3l160 160c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3L109.2 288 416 288c17.7 0 32-14.3 32-32s-14.3-32-32-32l-306.7 0L214.6 118.6c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0l-160 160z'
    }));
  }

  function IconPlay() {
    return React.createElement('svg', {
      stroke: 'currentColor', fill: '#4caf50', strokeWidth: '0', viewBox: '0 0 448 512',
      height: '1em', width: '1em', style: { display: 'inline-block', verticalAlign: 'middle' }
    }, React.createElement('path', {
      d: 'M424.4 214.7L72.4 6.6C43.8-10.3 0 6.1 0 47.9V464c0 37.5 40.7 60.1 72.4 41.3l352-208c31.4-18.5 31.5-64.1 0-82.6z'
    }));
  }

  function IconStop() {
    return React.createElement('svg', {
      stroke: 'currentColor', fill: '#f44336', strokeWidth: '0', viewBox: '0 0 448 512',
      height: '1em', width: '1em', style: { display: 'inline-block', verticalAlign: 'middle' }
    }, React.createElement('path', {
      d: 'M400 32H48C21.5 32 0 53.5 0 80v352c0 26.5 21.5 48 48 48h352c26.5 0 48-21.5 48-48V80c0-26.5-21.5-48-48-48z'
    }));
  }

  function Content() {
    var stateArr = useState(null);
    var status = stateArr[0];
    var setStatus = stateArr[1];

    var busyArr = useState(false);
    var busy = busyArr[0];
    var setBusy = busyArr[1];

    useEffect(function () {
      getStatus().then(setStatus).catch(console.error);

      var listener = addEventListener("deckdisplay_status", function (newStatus) {
        setStatus(newStatus);
      });

      return function () {
        removeEventListener("deckdisplay_status", listener);
      };
    }, []);

    if (!status) {
      return React.createElement(PanelSection, { title: "Статус системы" },
        React.createElement(PanelSectionRow, null,
          React.createElement(Field, { label: "Загрузка состояния DeckDisplay..." })
        )
      );
    }

    var handleGadgetToggle = async function (val) {
      setBusy(true);
      try {
        var updated = await setGadgetEnabled(val);
        setStatus(updated);
        toaster.toast({
          title: "DeckDisplay",
          body: val ? "USB-Гаджет (CDC-NCM + HID) активирован" : "USB-Гаджет отключен",
        });
      } finally {
        setBusy(false);
      }
    };

    var handleStreamToggle = async function () {
      setBusy(true);
      try {
        var targetState = !status.client_running;
        var updated = await setStreamActive(targetState);
        setStatus(updated);
      } finally {
        setBusy(false);
      }
    };

    var handleTouchToggle = async function (val) {
      var updated = await setTouchEnabled(val);
      setStatus(updated);
    };

    var handleSettingChange = async function (patch) {
      var updated = await updateSettings(patch);
      setStatus(updated);
    };

    var portOptions = [
      { data: 5000, label: "UDP 5000 (По умолчанию)" },
      { data: 5001, label: "UDP 5001 (Резервный)" },
      { data: 5555, label: "UDP 5555" },
    ];

    var statusColor = status.usb_connected ? "#4caf50" : (status.gadget_active ? "#ff9800" : "#9e9e9e");
    var statusText = status.usb_connected ? "ONLINE" : (status.gadget_active ? "READY" : "OFF");
    var statusDesc = status.usb_connected
      ? ("ПК подключен (" + status.host_ip + " ⇄ " + status.deck_ip + ")")
      : (status.gadget_active ? "Ожидание кабеля USB-C от ПК..." : "USB-Гаджет выключен");

    return React.createElement('div', null,
      React.createElement(PanelSection, { title: "Управление монитором" },
        React.createElement(PanelSectionRow, null,
          React.createElement(Field, {
            label: "Статус подключения USB-C",
            description: statusDesc
          },
            React.createElement('span', {
              style: { color: statusColor, fontWeight: "bold" }
            }, statusText)
          )
        ),
        React.createElement(PanelSectionRow, null,
          React.createElement(ButtonItem, {
            layout: "below",
            disabled: busy || !status.binaries_installed,
            onClick: handleStreamToggle
          },
            React.createElement('div', {
              style: { display: "flex", alignItems: "center", justifyContent: "center", gap: "8px" }
            },
              status.client_running ? React.createElement(IconStop, null) : React.createElement(IconPlay, null),
              React.createElement('span', null,
                status.client_running
                  ? "Остановить экран (Вернуться в Steam)"
                  : "Открыть экран ПК (Запустить клиент)"
              )
            )
          )
        ),
        React.createElement(PanelSectionRow, null,
          React.createElement(ToggleField, {
            label: "Режим USB-Гаджета (NCM + HID)",
            description: "Эмуляция сетевой карты 10 Гбит/с и тачскрина",
            icon: React.createElement(IconUsb, null),
            checked: status.gadget_active,
            disabled: busy,
            onChange: handleGadgetToggle
          })
        ),
        React.createElement(PanelSectionRow, null,
          React.createElement(ToggleField, {
            label: "Сенсорный ввод (Touchscreen)",
            description: status.touch_running ? "Активен (/dev/hidg0)" : "Отключен",
            icon: React.createElement(IconTouch, null),
            checked: status.settings.touch_enabled,
            disabled: busy,
            onChange: handleTouchToggle
          })
        )
      ),

      React.createElement(PanelSection, { title: "Параметры Plug & Play" },
        React.createElement(PanelSectionRow, null,
          React.createElement(ToggleField, {
            label: "Автозапуск при подключении кабеля",
            description: "Открывать экран при подключении USB-C и закрывать при отключении",
            checked: status.settings.auto_plug_and_play,
            onChange: function (val) { handleSettingChange({ auto_plug_and_play: val }); }
          })
        ),
        React.createElement(PanelSectionRow, null,
          React.createElement(ToggleField, {
            label: "Активировать гаджет при старте SteamOS",
            description: "Поднимать интерфейс usb0 сразу после включения консоли",
            checked: status.settings.auto_enable_gadget_on_boot,
            onChange: function (val) { handleSettingChange({ auto_enable_gadget_on_boot: val }); }
          })
        ),
        React.createElement(PanelSectionRow, null,
          React.createElement(DropdownItem, {
            label: "Порт видеопотока",
            menuLabel: "Выберите порт UDP",
            rgOptions: portOptions,
            selectedOption: status.settings.udp_port,
            onChange: function (opt) { handleSettingChange({ udp_port: opt.data }); }
          })
        )
      ),

      React.createElement(PanelSection, { title: "Диагностика оборудования" },
        React.createElement(PanelSectionRow, null,
          React.createElement(Field, {
            label: "Контроллер UDC",
            description: status.udc_controller
          })
        ),
        React.createElement(PanelSectionRow, null,
          React.createElement(Field, {
            label: "Бинарные модули C/C++",
            description: status.binaries_installed
              ? "Установлены в " + (status.deck_ip ? "/home/deck/deckdisplay" : "steamos-client")
              : "Не найдены! Выполните make в steamos-client"
          })
        )
      )
    );
  }

  var pluginDef = definePlugin(function () {
    return {
      name: "DeckDisplay",
      titleView: React.createElement('div', {
        className: staticClasses.Title || "deckdisplay-title"
      }, "DeckDisplay Monitor"),
      content: React.createElement(Content, null),
      icon: React.createElement(IconDesktop, null),
      onDismount: function () {}
    };
  });

  return pluginDef;
})(window.SP_REACT, window.DFL, window.DECKY_API);
