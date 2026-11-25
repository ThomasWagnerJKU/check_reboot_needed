# check_reboot_needed

A Nagios/Icinga plugin that reports whether a Linux host needs a reboot, and for how many
days the reboot has been pending. Python 3 with the standard library only. It runs as an
unprivileged user (e.g. via `check_by_ssh`), on Debian, Ubuntu, Raspberry Pi OS and
openSUSE/SLES.

After a kernel update the new kernel only runs after a reboot; after a glibc or systemd update
the old libraries stay in memory until then. Package managers report this in different ways,
and only some of them leave a flag behind. This plugin collects the signals and alerts only
when a reboot has been pending longer than you allow, so you can plan reboots instead of being
alerted after every update round.

## How it works

| Signal | Source | Pending since |
|---|---|---|
| kernel | the newest installed kernel image in `/boot` (`vmlinuz-*`, `Image-*`, `vmlinux-*`) of the running kernel's flavor is not the running one (`uname -r`) | ctime of the image = time of installation |
| flag | `/run/reboot-required` (Debian/Ubuntu, with the packages from `/run/reboot-required.pkgs`), `/run/reboot-needed` (zypper) | mtime of the flag file |
| zypper | `zypper needs-rebooting` exits 102 (openSUSE/SLES: core libraries or services updated) | newest change of the rpm database |

The kernel signal matters on Debian: its kernel packages do not create `/run/reboot-required`
unless `unattended-upgrades` or `update-notifier-common` is installed.

The flavor is the trailing part of the release that starts with a letter (`amd64`, `generic`,
`default`, `rpi-v8`), so a Raspberry Pi 5 kernel (`rpi-2712`) next to the running `rpi-v8` one, or
an installed `-rt` kernel, does not count as "newer". Versions compare numerically
(`6.12.118` > `6.12.99`). The image's mtime is not used because package managers set it to the
build time.

The oldest pending reason decides the state; all reasons are listed (the others in the long
output). If the plugin cannot determine a signal (e.g. `zypper` fails) and finds no other
reason, the result is UNKNOWN.

## Usage

```sh
check_reboot_needed -w 7          # WARNING after 7 days, never CRITICAL
check_reboot_needed -w 7 -c 30
```

```
REBOOT OK - no reboot pending, up 7.9 days | pending_days=0.00;7;;0; uptime_days=7.90;;;0;
REBOOT OK - reboot pending for 1.2 days, up 2.3 days - kernel 6.12.118+deb13-amd64 installed, running 6.12.117+deb13-amd64 (since 2026-11-24 06:11) | pending_days=1.20;7;;0; uptime_days=2.34;;;0;
flag /run/reboot-required (linux-image-6.12.118+deb13-amd64) (since 2026-11-24 06:12)
REBOOT WARNING - reboot pending for 14.4 days, up 2.3 days - kernel 6.8.0-151-generic installed, running 6.8.0-149-generic (since 2026-11-11 01:43) | pending_days=14.42;7;;0; uptime_days=2.34;;;0;
```

| Option | Meaning | Default |
|---|---|---|
| `-w`, `--warning` | days a reboot may be pending before WARNING | `0` (at once) |
| `-c`, `--critical` | days a reboot may be pending before CRITICAL | never |
| `--no-zypper` | do not run `zypper needs-rebooting` | |
| `--zypper` | path of `zypper` | searched in `PATH` |
| `-t`, `--timeout` | timeout for `zypper` in seconds | `40` |
| `-V`, `--version` | show the version | |

Perfdata: `pending_days` (with the thresholds) and `uptime_days`.

## Installation

Requirements: Python ≥ 3.7.

```sh
install -m 0755 check_reboot_needed /usr/lib/nagios/plugins/
install -m 0644 completions/check_reboot_needed /usr/share/bash-completion/completions/
```

Naemon/Nagios example (plugin on the monitored host, run via SSH):

```
define command {
  command_name   ssh_check_reboot_needed
  command_line   $USER1$/check_by_ssh -u naemon -t 60 -H $HOSTADDRESS$ -C "/usr/lib/nagios/plugins/check_reboot_needed $ARG1$"
}
define service {
  service_description   Reboot Needed
  hostgroup_name        linux-servers
  use                   generic-service
  check_command         ssh_check_reboot_needed!-w 7
  check_interval        60
}
```

## Tests

```sh
python3 -m unittest discover -s tests
```

The tests use a fake file tree and a fake `zypper`; nothing on the test machine is read.

## License

GPL-2.0-or-later, see [LICENSE](LICENSE).
