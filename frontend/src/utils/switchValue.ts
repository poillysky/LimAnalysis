/**
 * `<el-switch>` 事件值的类型归一。
 *
 * ── 为什么需要它 ──────────────────────────────────────────────────────
 * Element Plus 的 switch 在 `switch.d.ts:64` 声明的是：
 *   `change: (val: boolean | string | number) => boolean`
 * 也就是说，框架承认 change 可能抛出 string/number（自定义 active-value /
 * inactive-value 时确实会）。但项目里 4 个页面都在模板里把它硬写成
 * `@change="(v: boolean) => ..."` —— 那是**模板里的一句类型谎言**：
 *
 *   - 用普通 tsconfig（strict: false）编译时，这句谎言不报错；
 *   - 切到 strict 就立刻报 TS2322，因为 `(v: boolean) => void` 装不下
 *     `(val: string | number | boolean) => any`。
 *
 * 之前一直没报，不是它对，是类型检查没开。
 *
 * ── 怎么改的 ──────────────────────────────────────────────────────────
 * 不去改 4 个 handler 的签名（那会把 `string | number` 泄漏进业务逻辑，
 * 每个 handler 都要自己判类型），而是在模板这一层做一次显式归一：
 *
 *   `@change="v => onToggleEnable(switchValue(v))"`
 *
 * handler 签名保持 `boolean`，行为不变；类型也真的对上了。
 */

/** `<el-switch>` change 事件的原始载荷类型，与 Element Plus 声明保持一致 */
export type SwitchChangeValue = boolean | string | number;

/**
 * 把 el-switch 的 change 载荷归一为 boolean。
 *
 * 当前项目所有开关都用默认 active-value(true) / inactive-value(false)，
 * 所以运行时只会收到 boolean。这里仍按 Element Plus 的声明完整处理
 * string/number 两支，避免日后有人设了自定义值时静默出错。
 *
 * 注意 `"false"` 这类字符串按 JS 语义处理为 true —— 与
 * `Boolean("false") === true` 一致，不做「字符串语义」特判。
 */
export function switchValue(v: SwitchChangeValue): boolean {
  return typeof v === "boolean" ? v : Boolean(v);
}
