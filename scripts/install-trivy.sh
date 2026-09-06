#!/usr/bin/env bash
set -euo pipefail

version="0.74.0"
archive="trivy_${version}_Linux-64bit.tar.gz"
checksum="2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a"
install_dir="${1:?usage: install-trivy.sh INSTALL_DIRECTORY}"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

curl --fail --location --silent --show-error \
  --retry 3 --retry-all-errors --connect-timeout 10 --max-time 300 \
  "https://github.com/aquasecurity/trivy/releases/download/v${version}/${archive}" \
  --output "$work_dir/$archive"
echo "$checksum  $work_dir/$archive" | sha256sum --check
tar --no-same-owner -xzf "$work_dir/$archive" -C "$work_dir" trivy
install -d "$install_dir"
install -m 0755 "$work_dir/trivy" "$install_dir/trivy"
