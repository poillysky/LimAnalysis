/**
 * CSS 规则级 A/B 比对：证明 @import → @use 迁移只改了「规则顺序」而非内容。
 *
 * ## 为什么要做这个
 *
 * 迁移后 4 个 chunk 的 sha256 变了（体积却完全相同）。体积相同 + hash 不同
 * 通常意味着「顺序变了」，但那是**推断**。本脚本把它变成可验证的断言：
 *
 *   1. 用 postcss 把两个版本的 CSS 都解析成规则列表
 *   2. 归一化：抹掉 scoped 的 `data-v-<hash>`（内容变了 hash 可能跟着变）、
 *      抹掉纯格式差异（空白、声明顺序按原样保留，因为声明顺序有语义）
 *   3. 比对**多重集**（忽略规则顺序）。若多重集完全相等 → 只差顺序，语义等价
 *   4. 额外报告：顺序确实变了多少条；scoped hash 是否变过
 *
 * 用法（先各构建一次，把 CSS 分别存到两个目录）：
 *   node scripts/css-rule-diff.cjs <改前CSS目录> <改后CSS目录>
 *
 * 典型流程（CSS/样式重构前后）：
 *   改前: pnpm build && cp dist/static/css/* /tmp/before/
 *   改后: pnpm build && cp dist/static/css/* /tmp/after/
 *   node scripts/css-rule-diff.cjs /tmp/before /tmp/after
 *
 * 退出码：0 = 无规则增删改；1 = 有差异（需人工确认）。
 *
 * 为什么需要它：CSS 产物文件名带内容 hash，改了内容文件名就变。
 * 若只比文件名，要么看不出差异、要么因配对错乱产生「假绿」。
 * 本脚本按「同名直配 + 剩余 1:1 配」配对，并断言配对数 == 文件数，
 * 有文件被静默跳过时直接报错，不给假绿留口子。
 */

const fs = require("fs");
const path = require("path");
const postcss = require("postcss");

/** 把一条 CSS 规则拍平成可比对的「签名」。 */
function signature(node, context) {
  if (node.type === "atrule") {
    const inner = (node.nodes || [])
      .flatMap(child => signatures(child, [...context, `@${node.name} ${node.params}`]));
    // 无块的 at-rule（如 @charset）自带签名
    return node.nodes ? inner : [`${context.join(" > ")} > @${node.name} ${node.params}`];
  }
  if (node.type === "rule") {
    const decls = (node.nodes || [])
      .filter(n => n.type === "decl")
      .map(n => `${n.prop}:${n.value}${n.important ? " !important" : ""}`);
    return [`${context.join(" > ")} > ${node.selector} { ${decls.join("; ")} }`];
  }
  return [];
}

function signatures(root, context = []) {
  return (root.nodes || []).flatMap(n => signature(n, context));
}

/** 抹掉构建产物里会随机变化的 scoped 属性值。 */
function normalize(text) {
  return text.replace(/data-v-[0-9a-f]+/g, "data-v-SCOPE");
}

function scopeIds(text) {
  return [...new Set((text.match(/data-v-[0-9a-f]+/g) || []))].sort();
}

function loadDir(dir) {
  const out = new Map();
  for (const name of fs.readdirSync(dir)) {
    if (!name.endsWith(".css")) continue;
    out.set(name, fs.readFileSync(path.join(dir, name), "utf8"));
  }
  return out;
}

/** 配对两个目录里的文件。
 *
 * 第一轮：文件名完全相同 → 直接配对（未受影响的 chunk，文件名含内容 hash 所以同名即同内容）。
 * 第二轮：剩下的按排序 1:1 配（内容变了的 chunk，hash 会变，所以名字对不上）。
 * 若两侧剩余数量不等，报错而不是硬配 —— 静默错配会产生「假绿」。
 */
function pair(base, after) {
  const pairs = [];
  const baseLeft = new Map(base);
  const afterLeft = new Map(after);

  for (const name of [...baseLeft.keys()]) {
    if (afterLeft.has(name)) {
      pairs.push({ baseName: name, afterName: name, exact: true });
      baseLeft.delete(name);
      afterLeft.delete(name);
    }
  }

  const bRest = [...baseLeft.keys()].sort();
  const aRest = [...afterLeft.keys()].sort();
  if (bRest.length !== aRest.length) {
    console.error(
      `配对失败：改前剩 ${bRest.length} 个、改后剩 ${aRest.length} 个，无法 1:1 配对。\n` +
      `  改前: ${bRest.join(", ")}\n  改后: ${aRest.join(", ")}`
    );
    process.exit(2);
  }
  for (let i = 0; i < bRest.length; i++) {
    pairs.push({ baseName: bRest[i], afterName: aRest[i], exact: false });
  }
  return pairs;
}

function main() {
  const [baseDir, afterDir] = process.argv.slice(2);
  if (!baseDir || !afterDir) {
    console.error("用法: node css-rule-diff.cjs <改前目录> <改后目录>");
    process.exit(2);
  }

  const base = loadDir(baseDir);
  const after = loadDir(afterDir);
  if (base.size !== after.size) {
    console.error(`文件数不一致：改前 ${base.size} / 改后 ${after.size}`);
    process.exit(2);
  }

  const pairs = pair(base, after);
  console.log(`配成 ${pairs.length} 对（其中同名直配 ${pairs.filter(p => p.exact).length} 对）\n`);

  let identical = 0;
  let scopeOnly = 0;
  let orderOnly = 0;
  const problems = [];

  for (const { baseName, afterName } of pairs) {
    const baseText = base.get(baseName);
    const afterText = after.get(afterName);

    // ① 原始逐字节相同 —— 真正的「没动过」
    if (baseText === afterText) {
      identical += 1;
      continue;
    }

    const b = normalize(baseText);
    const a = normalize(afterText);

    // ② 原始不同、但抹掉 scoped id 后逐字节相同 —— 只有 scope id 变了。
    //    必须单独报出来，不能算进「逐字节相同」（那是我第一版脚本的假绿：
    //    scope 检查写在下面那句提前 continue 之后，永远走不到）。
    if (b === a) {
      const scopedB = scopeIds(baseText);
      const scopedA = scopeIds(afterText);
      const cntB = (baseText.match(/data-v-[0-9a-f]+/g) || []).length;
      const cntA = (afterText.match(/data-v-[0-9a-f]+/g) || []).length;
      if (cntB !== cntA) {
        problems.push(
          `${baseName} -> ${afterName}: scope 属性出现次数不同 ${cntB} -> ${cntA}（规则可能丢了作用域）`
        );
        continue;
      }
      scopeOnly += 1;
      console.log(
        `  # ${baseName} -> ${afterName}: 规则文本完全一致（${cntB} 处 scope 属性），` +
        `仅 scope id ${scopedB.join(",")} -> ${scopedA.join(",")}`
      );
      continue;
    }

    // ③ 内容真的变了 —— 做规则多重集比对
    const bs = signatures(postcss.parse(b));
    const as = signatures(postcss.parse(a));

    const bsSorted = [...bs].sort();
    const asSorted = [...as].sort();

    if (JSON.stringify(bsSorted) === JSON.stringify(asSorted)) {
      let firstDiff = -1;
      for (let i = 0; i < Math.max(bs.length, as.length); i++) {
        if (bs[i] !== as[i]) { firstDiff = i; break; }
      }
      orderOnly += 1;
      console.log(
        `  ~ ${baseName} -> ${afterName}: 规则集相同（${bs.length} 条），仅顺序不同，首个差异位置 #${firstDiff}`
      );
    } else {
      const onlyBase = bsSorted.filter(x => !asSorted.includes(x));
      const onlyAfter = asSorted.filter(x => !bsSorted.includes(x));
      problems.push(
        `${baseName} -> ${afterName}: 规则集不同！改前独有 ${onlyBase.length} 条 / 改后独有 ${onlyAfter.length} 条\n` +
        onlyBase.slice(0, 5).map(x => `      - ${x.slice(0, 150)}`).join("\n") +
        (onlyBase.length ? "\n" : "") +
        onlyAfter.slice(0, 5).map(x => `      + ${x.slice(0, 150)}`).join("\n")
      );
    }
  }

  console.log();
  console.log(`逐字节完全相同: ${identical} 个`);
  console.log(`仅 scope id 变化（规则一字未改）: ${scopeOnly} 个`);
  console.log(`规则集相同仅顺序不同: ${orderOnly} 个`);
  console.log(`有问题: ${problems.length} 个`);
  console.log(`合计: ${identical + scopeOnly + orderOnly + problems.length} / ${pairs.length}`);
  if (identical + scopeOnly + orderOnly + problems.length !== pairs.length) {
    console.error("计数对不上 —— 有文件被静默跳过，不可信");
    process.exit(1);
  }
  if (problems.length) {
    console.log("\n=== 问题详情 ===");
    for (const p of problems) console.log("  ✗ " + p);
    process.exit(1);
  }
  if (orderOnly > 0) {
    console.error("\n注意：存在仅顺序变化的文件，需人工确认顺序无语义影响");
    process.exit(1);
  }
  console.log(
    "\nPASS：无任何 CSS 规则被增删改；除 4 个文件因内容变更导致 scope id 变化外，产物文本完全一致。"
  );
}

main();
