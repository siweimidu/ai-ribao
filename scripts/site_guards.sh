#!/usr/bin/env bash
# Guards for the generated site.
#
# The first guard exists because of a real miss: a TypeScript-style annotation
# (`(id: string) =>`) was left in `assets/motion.js`. Browsers refuse to parse the whole
# file, so every interaction on the page died silently -- search, theme, calendar, TOC
# highlighting -- and the entire Python test suite still passed, because nothing checked
# the JavaScript at all. A page whose JS does not parse is not a partially working page.
#
# Runs under real bash, and `node --check` is used rather than a regex because parsing is
# what we actually want to assert.
set -uo pipefail

fail=0
ok()   { printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=1; }

echo "site guards"

# --- 1. JavaScript must parse ------------------------------------------------------
if ! command -v node >/dev/null 2>&1; then
  echo "  --   node not found, skipping JS syntax check"
else
  js_bad=0
  while IFS= read -r file; do
    # `node --check` exits non-zero on a syntax error and prints the reason.
    if ! out=$(node --check "$file" 2>&1); then
      bad "$file 语法错误"
      printf '       %s\n' "$(printf '%s' "$out" | head -n 3)"
      js_bad=1
    fi
  done < <(find site/assets -name '*.js' -type f | sort)
  [ "$js_bad" = 0 ] && ok "$(find site/assets -name '*.js' | wc -l | tr -d ' ') 个 JS 文件语法正确"
fi

# --- 2. No TypeScript syntax in shipped JavaScript ---------------------------------
# A parser would catch it, but the message here names the actual mistake.
ts_hits=$(grep -rnE '\((id|el|e|a|t|s|v|x|y|n|i|k|dt|d|cb|fn|cfg|opts|args|node|item|event|target|opener): *[A-Za-z]' site/assets/*.js 2>/dev/null | grep -v '^\s*//' || true)
if [ -n "$ts_hits" ]; then
  bad "JavaScript 里出现 TypeScript 类型标注（浏览器会整份拒绝解析）"
  printf '%s\n' "$ts_hits" | head -n 5 | sed 's/^/       /'
else
  ok "无 TypeScript 语法残留"
fi

# --- 3. Every asset the page references must exist ---------------------------------
# The same class of bug as the feed 404: the page linked `feed/zh.xml` for weeks while the
# deploy never uploaded it.
site_dir="data/digests/site"
if [ -d "$site_dir" ]; then
  missing=0
  for page in "$site_dir"/*.html; do
    [ -e "$page" ] || continue
    while IFS= read -r ref; do
      case "$ref" in
        http*|data:*|mailto:*|'//'*|\#*|'') continue ;;
      esac
      target="${ref%%\?*}"
      target="${target%%\#*}"
      [ -e "$site_dir/$target" ] || { echo "       $page -> $target"; missing=1; }
    done < <(grep -oE 'href="[^"]+"' "$page" | sed 's/^href="//; s/"$//' | sort -u)
  done
  [ "$missing" = 0 ] && ok "页面引用的相对路径都存在" || bad "页面引用了产物里不存在的路径"
else
  echo "  --   $site_dir 不存在，跳过链接检查"
fi

# --- 4. Assets in the artifact must match their source ------------------------------
# `site/assets` is the source, `data/digests/site/assets` is the built copy, and the deploy
# uploads the copy. Editing the source and measuring the copy reported good numbers for a
# build that no longer existed -- twice.
drift=0
for src in site/assets/*; do
  [ -f "$src" ] || continue
  name=$(basename "$src")
  built="$site_dir/assets/$name"
  if [ ! -f "$built" ]; then
    echo "       $name 未拷贝到产物目录"; drift=1
  elif ! cmp -s "$src" "$built"; then
    echo "       $name 与源不一致"; drift=1
  fi
done
[ "$drift" = 0 ] && ok "产物资源与源一致" || bad "产物资源陈旧（用 --no-llm 重渲染，--no-deliver 不拷贝资源）"

exit "$fail"
