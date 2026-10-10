#!/usr/bin/env bash
#
# Check the deploy-onboarding readiness manifest and surface what's missing.
#
# Verifies presence (never values) of the secrets/variables a fork needs before
# the deploy + integration-test required checks can be enabled, and validates the
# fork-owned service descriptor (ADR-039). Opens/updates a single `human-required`
# tracking issue listing what's missing and who owns it; closes that issue when
# everything is present.
#
# Service-specific build and test values are validated through `.spi/service.yaml`.
# Only environment bindings written by `spi onboard` are checked here.
#
# Arguments:
#   $1            Repository full name (owner/repo)
#   --dry-run     Print the assessment without opening/closing the issue
#
# Environment:
#   GH_TOKEN      Token with repository-variable read + issues:write
#
# `spi onboard` writes AZURE_CLIENT_ID as both a secret (consumed by azure/login)
# and a non-sensitive variable (workflow gate + repo-to-cluster link). GitHub App
# installation tokens cannot enumerate Actions secret names unless the App has a
# separate Secrets permission, so the paired variable is the durable readiness
# marker here. A missing secret still fails explicitly in azure/login.
# Descriptor findings are reported as field paths + stable error codes only, so no
# descriptor or secret value ever reaches the issue body.

set -euo pipefail

DRY_RUN=false
ARGS=()
for a in "$@"; do
  if [[ "$a" == "--dry-run" ]]; then DRY_RUN=true; else ARGS+=("$a"); fi
done
if [[ ${#ARGS[@]} -lt 1 ]]; then
  echo "Usage: $0 <repo_full_name> [--dry-run]"; exit 1
fi
REPO="${ARGS[0]}"
export GH_TOKEN="${GH_TOKEN:-}"

ISSUE_TITLE="⚙️ Deploy onboarding: required CI configuration missing"

variables_json="$(gh api --paginate --slurp "repos/${REPO}/actions/variables?per_page=100" 2>/dev/null || echo '[{"variables":[]}]')"
variable_names="$(jq -r '.[].variables[].name' <<< "$variables_json")"
READ_SERVICE_CONFIG=".github/scripts/service-config/read_service_config.py"
config_json=""
acceptance_config=""
if [[ -f "$READ_SERVICE_CONFIG" ]]; then
  config_json="$(python3 "$READ_SERVICE_CONFIG" --root . --format json --redact 2>/dev/null || true)"
  if [[ -n "$config_json" ]] && jq empty <<< "$config_json" 2>/dev/null; then
    acceptance_config="$(jq -r '.acceptance_config // ""' <<< "$config_json")"
  fi
fi

missing=()
have_var()    { grep -qx "$1" <<< "$variable_names"; }
var_value() {
  jq -r --arg name "$1" '[.[].variables[] | select(.name == $name) | .value][0] // ""' \
    <<< "$variables_json"
}

have_var "AZURE_CLIENT_ID" || missing+=("deploy identity \`AZURE_CLIENT_ID\` — set by \`spi onboard\`")
for v in AAD_CLIENT_ID AKS_RESOURCE_GROUP AKS_CLUSTER_NAME K8S_NAMESPACE FLUX_NAMESPACE \
  K8S_DEPLOYMENT_NAME K8S_CONTAINER_NAME GATEWAY_URL DATA_PARTITION_ID; do
  have_var "$v" || missing+=("variable \`$v\` — set by \`spi onboard\`")
done
[[ "$(var_value DEPLOY_VALIDATED)" == "true" ]] \
  || missing+=("successful first canary \`DEPLOY_VALIDATED=true\` — set by \`spi onboard --verify\`")

if [[ -z "$acceptance_config" ]] || ! jq -e 'type == "object"' >/dev/null 2>&1 <<< "$acceptance_config"; then
  missing+=("descriptor field \`tests.acceptance\` — complete branch-tracked live-test contract")
else
  if [[ "$(jq -r '.keyVaultBindings | length' <<< "$acceptance_config")" -gt 0 ]]; then
    have_var KEYVAULT_NAME \
      || missing+=("variable \`KEYVAULT_NAME\` — required by descriptor keyVaultBindings")
  fi
  if [[ -n "$(jq -r '.noDataAccessTokenEnv // ""' <<< "$acceptance_config")" ]]; then
    have_var NO_DATA_ACCESS_TESTER_CLIENT_ID \
      || missing+=("variable \`NO_DATA_ACCESS_TESTER_CLIENT_ID\` — set by \`spi onboard\` for negative-authorization tests")
  fi
  while IFS= read -r source; do
    case "$source" in
      entitlementDomain)
        have_var ENTITLEMENT_DOMAIN \
          || missing+=("variable \`ENTITLEMENT_DOMAIN\` — discovered by \`spi onboard\`")
        ;;
      storageAccount)
        have_var STORAGE_ACCOUNT_NAME \
          || missing+=("variable \`STORAGE_ACCOUNT_NAME\` — discovered by \`spi onboard\`")
        ;;
    esac
  done < <(jq -r '.bindings | to_entries[].value.source' <<< "$acceptance_config")
fi

# --- Service descriptor + descriptor ownership (ADR-039) ---------------------
# Reported through this same deduplicated issue rather than a competing tracker.
if [[ -f "$READ_SERVICE_CONFIG" ]]; then
  if [[ -z "$config_json" ]] || ! jq empty <<< "$config_json" 2>/dev/null; then
    missing+=("service descriptor could not be evaluated — run \`python3 $READ_SERVICE_CONFIG --root . --format json\` locally")
  else
    descriptor_present="$(jq -r '.descriptor_present' <<< "$config_json")"
    descriptor_valid="$(jq -r '.valid' <<< "$config_json")"
    lane_implemented="$(jq -r '.lane_implemented' <<< "$config_json")"
    archetype="$(jq -r '.archetype' <<< "$config_json")"
    if [[ "$descriptor_present" != "true" ]]; then
      missing+=("service descriptor \`.spi/service.yaml\` — generate with \`python3 .github/scripts/service-config/generate_descriptor.py --root .\` (legacy Java inference is in use)")
    elif [[ "$descriptor_valid" != "true" ]]; then
      codes="$(jq -r '[.errors[]] | join("; ")' <<< "$config_json")"
      missing+=("service descriptor \`.spi/service.yaml\` is invalid — $codes")
    elif [[ "$lane_implemented" != "true" ]]; then
      missing+=("archetype \`$archetype\` has no build lane in this template version — apply the latest template-sync PR before enabling required checks")
    fi
  fi
fi

GENERATE_CODEOWNERS=".github/scripts/service-config/generate_codeowners.py"
if [[ -f "$GENERATE_CODEOWNERS" ]]; then
  if ! python3 "$GENERATE_CODEOWNERS" --path CODEOWNERS --check >/dev/null 2>&1; then
    missing+=("CODEOWNERS rule for \`/.spi/\` — set variable \`SPI_ENGINEERING_OWNERS\`, then run \`python3 .github/scripts/service-config/generate_codeowners.py --path CODEOWNERS --owners \"@org/team\"\` and commit the result")
  fi
fi

existing_issue="$(gh issue list --repo "$REPO" --state open --search "in:title \"$ISSUE_TITLE\"" --json number --jq '.[0].number // empty' 2>/dev/null || echo "")"

if [[ ${#missing[@]} -eq 0 ]]; then
  echo "✅ Deploy-onboarding manifest complete."
  if [[ -n "$existing_issue" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
      echo "DRY-RUN would close issue #$existing_issue (manifest now complete)"
    else
      gh issue close "$existing_issue" --repo "$REPO" --comment "All required deploy-onboarding configuration is now present. Closing." || true
    fi
  fi
  exit 0
fi

echo "⚠️ Missing ${#missing[@]} required item(s) for deploy onboarding:"
printf '   - %s\n' "${missing[@]}"

body="$(printf 'The deploy and integration-test required checks stay disabled until the following are set on this repository:\n\n'; printf -- '- [ ] %s\n' "${missing[@]}"; printf '\nService-specific build and acceptance-test configuration belongs in `.spi/service.yaml`; environment identity and cluster bindings are written by `spi onboard`.\nService-descriptor findings list field paths and error codes only; no descriptor, secret or variable value is reproduced here.\n\n_Maintained automatically by `settings-apply.yml`._\n')"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "DRY-RUN would $( [[ -n "$existing_issue" ]] && echo "update issue #$existing_issue" || echo "open a human-required issue" )"
  exit 0
fi

if [[ -n "$existing_issue" ]]; then
  gh issue edit "$existing_issue" --repo "$REPO" --body "$body" >/dev/null
  echo "Updated tracking issue #$existing_issue"
else
  gh issue create --repo "$REPO" --title "$ISSUE_TITLE" --body "$body" \
    --label "human-required" >/dev/null 2>&1 \
    || gh issue create --repo "$REPO" --title "$ISSUE_TITLE" --body "$body" >/dev/null
  echo "Opened human-required tracking issue."
fi
