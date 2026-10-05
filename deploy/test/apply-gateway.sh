#!/bin/sh
# Run as root on the already inspected Ubuntu/Caddy test host.
set -eu

if [ "$(id -u)" -ne 0 ]; then
  printf '%s\n' 'Run this script with sudo on the test host.' >&2
  exit 1
fi

task_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
main_config=/etc/caddy/Caddyfile
site_config=/etc/caddy/sites/openform-test.caddy
site_import='import /etc/caddy/sites/openform-test.caddy'
backup_dir="/var/backups/openform-gateway/$(date -u +%Y%m%dT%H%M%SZ)-$$"

test -f "$main_config"
test -f "$task_dir/openform-test.caddy"
command -v caddy >/dev/null
systemctl is-active --quiet caddy
install -d -m 0700 "$backup_dir"
cp -a "$main_config" "$backup_dir/Caddyfile"
had_site=0
if [ -f "$site_config" ]; then
  cp -a "$site_config" "$backup_dir/openform-test.caddy"
  had_site=1
fi

finished=0
rollback() {
  status=$?
  if [ "$finished" -ne 1 ]; then
    cp -a "$backup_dir/Caddyfile" "$main_config"
    if [ "$had_site" -eq 1 ]; then
      cp -a "$backup_dir/openform-test.caddy" "$site_config"
    else
      rm -f "$site_config"
    fi
    systemctl reload caddy || true
    printf '%s\n' "Gateway update failed; restored config from $backup_dir." >&2
  fi
  exit "$status"
}
trap rollback EXIT

install -d -m 0755 /etc/caddy/sites
install -m 0644 "$task_dir/openform-test.caddy" "$site_config"
if ! grep -Fqx "$site_import" "$main_config"; then
  printf '\n%s\n' "$site_import" >> "$main_config"
fi
caddy fmt --overwrite "$site_config"
caddy validate --config "$main_config" --adapter caddyfile
systemctl reload caddy
systemctl is-active --quiet caddy

install -d -m 0750 -o ubuntu -g ubuntu /srv/openform /srv/openform/releases
install -d -m 0700 -o ubuntu -g ubuntu /srv/openform/data /srv/openform/backups
finished=1
printf '%s\n' "OpenForm gateway reloaded; previous configuration: $backup_dir"
