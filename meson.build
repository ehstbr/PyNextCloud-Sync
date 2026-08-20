project(
  'pynextcloud-sync',
  version: '0.1.32',
  meson_version: '>= 1.0.0',
)

gnome = import('gnome')
i18n = import('i18n')
python = import('python').find_installation('python3')

python_sources = files(
  'src/pynextcloud_sync/__init__.py',
  'src/pynextcloud_sync/__main__.py',
  'src/pynextcloud_sync/application.py',
  'src/pynextcloud_sync/core/__init__.py',
  'src/pynextcloud_sync/core/autostart.py',
  'src/pynextcloud_sync/core/bootstrap.py',
  'src/pynextcloud_sync/core/desktop_integration.py',
  'src/pynextcloud_sync/core/exclusions.py',
  'src/pynextcloud_sync/core/inotify.py',
  'src/pynextcloud_sync/core/network.py',
  'src/pynextcloud_sync/core/power.py',
  'src/pynextcloud_sync/core/runtime.py',
  'src/pynextcloud_sync/core/scheduler.py',
  'src/pynextcloud_sync/core/safety.py',
  'src/pynextcloud_sync/core/state.py',
  'src/pynextcloud_sync/core/suspend.py',
  'src/pynextcloud_sync/core/sync_engine.py',
  'src/pynextcloud_sync/core/sync_run_marker.py',
  'src/pynextcloud_sync/core/timers.py',
  'src/pynextcloud_sync/core/triggers.py',
  'src/pynextcloud_sync/core/updates.py',
  'src/pynextcloud_sync/core/window_presentation.py',
  'src/pynextcloud_sync/nextcloud/__init__.py',
  'src/pynextcloud_sync/nextcloud/api.py',
  'src/pynextcloud_sync/nextcloud/command.py',
  'src/pynextcloud_sync/nextcloud/credentials.py',
  'src/pynextcloud_sync/nextcloud/device_identity.py',
  'src/pynextcloud_sync/nextcloud/details_refresher.py',
  'src/pynextcloud_sync/nextcloud/http.py',
  'src/pynextcloud_sync/nextcloud/login_flow.py',
  'src/pynextcloud_sync/nextcloud/models.py',
  'src/pynextcloud_sync/nextcloud/push.py',
  'src/pynextcloud_sync/nextcloud/push_protocol.py',
  'src/pynextcloud_sync/storage/__init__.py',
  'src/pynextcloud_sync/storage/config.py',
  'src/pynextcloud_sync/storage/log.py',
  'src/pynextcloud_sync/storage/remote_details.py',
  'src/pynextcloud_sync/ui/__init__.py',
  'src/pynextcloud_sync/ui/about.py',
  'src/pynextcloud_sync/ui/about_content.py',
  'src/pynextcloud_sync/ui/activity.py',
  'src/pynextcloud_sync/ui/bootstrap.py',
  'src/pynextcloud_sync/ui/log_view.py',
  'src/pynextcloud_sync/ui/main_window.py',
  'src/pynextcloud_sync/ui/reconnect.py',
  'src/pynextcloud_sync/ui/settings.py',
  'src/pynextcloud_sync/ui/setup.py',
  'src/pynextcloud_sync/ui/tray.py',
  'src/pynextcloud_sync/ui/tray_state.py',
  'src/pynextcloud_sync/ui/update_window.py',
  'src/pynextcloud_sync/util/__init__.py',
  'src/pynextcloud_sync/util/i18n.py',
  'src/pynextcloud_sync/util/paths.py',
  'src/pynextcloud_sync/util/redact.py',
)

python.install_sources(
  files(
    'src/pynextcloud_sync/__init__.py',
    'src/pynextcloud_sync/__main__.py',
    'src/pynextcloud_sync/application.py',
  ),
  subdir: 'pynextcloud_sync',
  pure: true,
)
python.install_sources(
  files(
    'src/pynextcloud_sync/core/__init__.py',
    'src/pynextcloud_sync/core/autostart.py',
    'src/pynextcloud_sync/core/bootstrap.py',
    'src/pynextcloud_sync/core/desktop_integration.py',
    'src/pynextcloud_sync/core/exclusions.py',
    'src/pynextcloud_sync/core/inotify.py',
    'src/pynextcloud_sync/core/network.py',
    'src/pynextcloud_sync/core/power.py',
    'src/pynextcloud_sync/core/runtime.py',
    'src/pynextcloud_sync/core/scheduler.py',
    'src/pynextcloud_sync/core/safety.py',
    'src/pynextcloud_sync/core/state.py',
    'src/pynextcloud_sync/core/suspend.py',
    'src/pynextcloud_sync/core/sync_engine.py',
    'src/pynextcloud_sync/core/sync_run_marker.py',
    'src/pynextcloud_sync/core/timers.py',
    'src/pynextcloud_sync/core/triggers.py',
    'src/pynextcloud_sync/core/updates.py',
    'src/pynextcloud_sync/core/window_presentation.py',
  ),
  subdir: 'pynextcloud_sync/core',
  pure: true,
)
python.install_sources(
  files(
    'src/pynextcloud_sync/nextcloud/__init__.py',
    'src/pynextcloud_sync/nextcloud/api.py',
    'src/pynextcloud_sync/nextcloud/command.py',
    'src/pynextcloud_sync/nextcloud/credentials.py',
    'src/pynextcloud_sync/nextcloud/device_identity.py',
    'src/pynextcloud_sync/nextcloud/details_refresher.py',
    'src/pynextcloud_sync/nextcloud/http.py',
    'src/pynextcloud_sync/nextcloud/login_flow.py',
    'src/pynextcloud_sync/nextcloud/models.py',
    'src/pynextcloud_sync/nextcloud/push.py',
    'src/pynextcloud_sync/nextcloud/push_protocol.py',
  ),
  subdir: 'pynextcloud_sync/nextcloud',
  pure: true,
)
python.install_sources(
  files(
    'src/pynextcloud_sync/storage/__init__.py',
    'src/pynextcloud_sync/storage/config.py',
    'src/pynextcloud_sync/storage/log.py',
    'src/pynextcloud_sync/storage/remote_details.py',
  ),
  subdir: 'pynextcloud_sync/storage',
  pure: true,
)
python.install_sources(
  files(
    'src/pynextcloud_sync/ui/__init__.py',
    'src/pynextcloud_sync/ui/about.py',
    'src/pynextcloud_sync/ui/about_content.py',
    'src/pynextcloud_sync/ui/activity.py',
    'src/pynextcloud_sync/ui/bootstrap.py',
    'src/pynextcloud_sync/ui/log_view.py',
    'src/pynextcloud_sync/ui/main_window.py',
    'src/pynextcloud_sync/ui/reconnect.py',
    'src/pynextcloud_sync/ui/settings.py',
    'src/pynextcloud_sync/ui/setup.py',
    'src/pynextcloud_sync/ui/tray.py',
    'src/pynextcloud_sync/ui/tray_state.py',
    'src/pynextcloud_sync/ui/update_window.py',
  ),
  subdir: 'pynextcloud_sync/ui',
  pure: true,
)
python.install_sources(
  files(
    'src/pynextcloud_sync/util/__init__.py',
    'src/pynextcloud_sync/util/i18n.py',
    'src/pynextcloud_sync/util/paths.py',
    'src/pynextcloud_sync/util/redact.py',
  ),
  subdir: 'pynextcloud_sync/util',
  pure: true,
)

launcher_configuration = configuration_data()
launcher_configuration.set('PYTHON', python.full_path())
configure_file(
  input: 'data/pynextcloud-sync.in',
  output: 'pynextcloud-sync',
  configuration: launcher_configuration,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: ['rwxr-xr-x'],
)

install_data(
  'data/com.eduhcommerce.PyNextCloudSync.desktop',
  install_dir: join_paths(get_option('datadir'), 'applications'),
)
install_data(
  'data/com.eduhcommerce.PyNextCloudSync.metainfo.xml',
  install_dir: join_paths(get_option('datadir'), 'metainfo'),
)
install_data(
  'data/icons/com.eduhcommerce.PyNextCloudSync.svg',
  install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'scalable', 'apps'),
)
install_data(
  'data/icons/com.eduhcommerce.PyNextCloudSync-symbolic.svg',
  install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'symbolic', 'apps'),
)
install_data(
  'data/icons/com.eduhcommerce.PyNextCloudSync-folder.svg',
  install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'scalable', 'places'),
)
install_subdir(
  'data/icons/status',
  install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'symbolic', 'status'),
  strip_directory: true,
)

install_data(
  'CHANGELOG.md',
  'LICENSE',
  'TERMS.md',
  'TERMS.pt-BR.md',
  'THIRD-PARTY.md',
  'THIRD-PARTY.pt-BR.md',
  'version.json',
  install_dir: join_paths(get_option('datadir'), 'doc', 'pynextcloud-sync'),
)

subdir('po')
