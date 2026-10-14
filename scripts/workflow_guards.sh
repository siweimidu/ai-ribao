#!/usr/bin/env bash
# Guards for the workflow shell, run against real bash.
#
# These exist because of a bug class that is invisible in review and silent in CI: the
# behaviour of `$?` after a pipeline.
#
# The daily workflow ran `python -m aidaily run ... | tee publish.log` and then read `code=$?`.
# GitHub Actions executes a `run:` block as `bash -e {0}` with **pipefail off**, so `$?` is
# `tee`'s status, and tee succeeded because it dutifully wrote the output. Consequences:
#
#   * a crash came back as 0, so the job reported success and the site simply did not
#     update -- indistinguishable from "nothing to publish today";
#   * the gate's exit code 10 (already published) also read as 0, so the `run=false` branch
#     was unreachable and every trigger treated a published day as fresh work.
#
# The fix is `${PIPESTATUS[0]}`, and this guard asserts no workflow goes back to `$?`.
#
# NOTE: this script deliberately does **not** enable `pipefail` (except around its own
# internal checks), because the behaviour under test only exists when it is off.
set -u

fail=0
ok()  { printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=1; }

cd "$(dirname "$0")/.." || exit 1
echo "workflow guards"

# --- 1. No `$?` immediately after a pipeline --------------------------------------
# Scanned line by line because the failure is positional: `$?` is correct in general and
# wrong only when the preceding line ends in a pipe.
hits=$(awk '
  /code=\$\?/ && prev ~ /\|[[:space:]]*tee/ { print FILENAME":"FNR": "$0 }
  { prev = $0 }
' .github/workflows/*.yml)

if [ -n "$hits" ]; then
  bad '管道之后用 $? 取退出码（pipefail 默认关闭，读到的是 tee 的状态）'
  printf '%s\n' "$hits" | sed 's/^/       /'
else
  ok '没有在管道后误用 $?'
fi

# --- 2. Every piped producer is read through PIPESTATUS ---------------------------
if grep -q 'PIPESTATUS\[0\]' .github/workflows/daily.yml; then
  ok 'daily.yml 通过 PIPESTATUS 取退出码'
else
  bad 'daily.yml 没有使用 PIPESTATUS 读取流水线退出码'
fi

# --- 3 & 4. The behaviour itself, demonstrated ------------------------------------
# A guard that only greps can pass while the pipeline semantics are still wrong, so the
# shell behaviour is exercised too. `set +o pipefail` is what makes this meaningful: with
# pipefail on, `$?` already reports the producer's status and the demonstration would
# "prove" the opposite of the bug.
set +o pipefail
set +e

( exit 7 ) | tee /dev/null >/dev/null
naive=$?
( exit 7 ) | tee /dev/null >/dev/null
real=${PIPESTATUS[0]}

if [ "$naive" = "0" ] && [ "$real" = "7" ]; then
  ok "\$? 掩盖崩溃（$naive）而 PIPESTATUS 如实报告（$real）—— 本守卫存在的原因"
else
  bad "对管道退出码的假设不成立：\$?=$naive PIPESTATUS=$real（pipefail 是否被打开？）"
fi

( exit 10 ) | tee /dev/null >/dev/null
naive10=$?
( exit 10 ) | tee /dev/null >/dev/null
real10=${PIPESTATUS[0]}
if [ "$real10" = "10" ] && [ "$naive10" = "0" ]; then
  ok '闸门的退出码 10 曾被 $? 吞掉，现在可区分'
else
  bad "退出码 10 传递异常：\$?=$naive10 PIPESTATUS=$real10"
fi

set -e

# --- 5. Secrets stay out of the workflow files ------------------------------------
if grep -qE 'sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{36}' .github/workflows/*.yml 2>/dev/null; then
  bad '工作流文件里出现疑似密钥'
else
  ok '工作流文件无密钥'
fi

exit "$fail"
