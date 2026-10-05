#!/bin/sh
# Run as root on the already inspected Ubuntu/Caddy QA host.
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
command -v flock >/dev/null
exec 9>/run/lock/caddy-config.lock
if ! flock -n 9; then
  printf '%s\n' 'Another Caddy configuration update is running; retry after it finishes.' >&2
  exit 1
fi
systemctl is-active --quiet caddy
install -d -m 0700 "$backup_dir"
cp -a "$main_config" "$backup_dir/Caddyfile"
had_site=0
if [ -f "$site_config" ]; then
  cp -a "$site_config" "$backup_dir/openform-test.caddy"
  had_site=1
fi

finished=0
main_changed=0
site_changed=0
main_stage=''
site_stage=''
rollback() {
  status=$?
  if [ "$finished" -ne 1 ]; then
    safe_reload=1
    if [ "$main_changed" -eq 1 ] || [ "$site_changed" -eq 1 ]; then
      if ! cmp -s "$backup_dir/Caddyfile.updated" "$main_config"; then
        safe_reload=0
        printf '%s\n' 'Main config changed outside this update; preserved it instead of restoring a stale snapshot.' >&2
      fi
    fi
    if [ "$site_changed" -eq 1 ]; then
      if ! cmp -s "$task_dir/openform-test.caddy" "$site_config"; then
        safe_reload=0
        printf '%s\n' 'Site config changed outside this update; preserved it for inspection.' >&2
      fi
    fi
    # Check the whole configuration pair before restoring either file.
    if [ "$safe_reload" -eq 1 ]; then
      if [ "$main_changed" -eq 1 ]; then
        cp -a "$backup_dir/Caddyfile" "$main_config"
      fi
      if [ "$site_changed" -eq 1 ]; then
        if [ "$had_site" -eq 1 ]; then
          cp -a "$backup_dir/openform-test.caddy" "$site_config"
        else
          rm -f "$site_config"
        fi
      fi
      if [ "$main_changed" -eq 1 ] || [ "$site_changed" -eq 1 ]; then
        systemctl reload caddy || true
      fi
    fi
    printf '%s\n' "Gateway update failed; backup for inspection: $backup_dir." >&2
  fi
  if [ -n "$main_stage" ]; then rm -f "$main_stage"; fi
  if [ -n "$site_stage" ]; then rm -f "$site_stage"; fi
  exit "$status"
}
trap rollback EXIT

install -d -m 0755 /etc/caddy/sites
caddy fmt --overwrite "$task_dir/openform-test.caddy"
# The old test site shared a backend with the apex domain. Detach only www;
# keep the other site's shared service and files available for its own domain.
sed 's/^openforgeai.cn, www.openforgeai.cn {$/openforgeai.cn {/' "$backup_dir/Caddyfile" > "$backup_dir/Caddyfile.updated"
if grep -Fq 'www.openforgeai.cn' "$backup_dir/Caddyfile.updated"; then
  printf '%s\n' 'An unexpected www site remains in the main config; inspect it before replacing this domain.' >&2
  exit 1
fi
if ! grep -Fqx "$site_import" "$backup_dir/Caddyfile.updated"; then
  printf '\n%s\n' "$site_import" >> "$backup_dir/Caddyfile.updated"
fi
main_stage=$(mktemp /etc/caddy/.openform-main.XXXXXX)
site_stage=$(mktemp /etc/caddy/sites/.openform-site.XXXXXX)
install -m 0644 "$backup_dir/Caddyfile.updated" "$main_stage"
install -m 0644 "$task_dir/openform-test.caddy" "$site_stage"
if ! cmp -s "$backup_dir/Caddyfile" "$main_config"; then
  printf '%s\n' 'Main config changed since the backup; stopped without replacing it.' >&2
  exit 1
fi
if [ "$had_site" -eq 1 ]; then
  if ! cmp -s "$backup_dir/openform-test.caddy" "$site_config"; then
    printf '%s\n' 'Site config changed since the backup; stopped without replacing it.' >&2
    exit 1
  fi
elif [ -e "$site_config" ]; then
  printf '%s\n' 'A site config appeared since the backup; stopped without replacing it.' >&2
  exit 1
fi
if ! cmp -s "$backup_dir/Caddyfile.updated" "$main_config"; then
  mv -f "$main_stage" "$main_config"
  main_changed=1
fi
mv -f "$site_stage" "$site_config"
site_changed=1
caddy validate --config "$main_config" --adapter caddyfile
systemctl reload caddy
systemctl is-active --quiet caddy

install -d -m 0750 -o ubuntu -g ubuntu /srv/openform /srv/openform/releases
install -d -m 0700 -o ubuntu -g ubuntu /srv/openform/data /srv/openform/backups
finished=1
printf '%s\n' "OpenForm QA gateway reloaded; previous configuration: $backup_dir"
