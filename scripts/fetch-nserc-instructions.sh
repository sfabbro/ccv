#!/bin/sh
# Download the current NSERC CCV instructions. The page is NSERC's; do not commit it.
url="https://nserc-crsng.canada.ca/en/funding/online-application-systems-and-tools/online-services/research-portal/instructions/how"
out="${1:-CCCV_NSERC_INSTRUCTIONS.html}"
curl -fsSL -A "ccv" -o "$out" "$url"
echo "Wrote $out"
