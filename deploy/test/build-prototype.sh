#!/bin/sh
# Package only the public prototype runtime and its licensed assets.
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
output_dir=${1:?Usage: sh deploy/test/build-prototype.sh /absolute/new/output-directory}
case "$output_dir" in
  /*) ;;
  *) printf '%s\n' 'Output directory must be an absolute path.' >&2; exit 1 ;;
esac
if [ -e "$output_dir" ]; then
  printf '%s\n' 'Output directory already exists; choose a new directory.' >&2
  exit 1
fi

mkdir -p "$output_dir/prototype/vendor" "$output_dir/assets/brand/svg"
for filename in index.html base.css integrated.css app.mjs model.mjs store.mjs teacher.mjs admin.mjs student.mjs ui.mjs icons.mjs; do
  cp "$repository_dir/prototype/$filename" "$output_dir/prototype/$filename"
done
cp "$repository_dir/prototype/vendor/qrcode.js" "$repository_dir/prototype/vendor/LICENSE-qrcode.txt" "$output_dir/prototype/vendor/"
for asset in "$repository_dir"/assets/brand/svg/*.svg; do
  cp "$asset" "$output_dir/assets/brand/svg/"
done
cp "$repository_dir/LICENSE" "$output_dir/LICENSE"
find "$output_dir" -type d -exec chmod 0755 {} +
find "$output_dir" -type f -exec chmod 0644 {} +
printf '%s\n' "Public prototype packaged in $output_dir. No repository, tests, private data or secrets included."
