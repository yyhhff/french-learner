/* Wave 0 (TASK-0064): 本文件的 2927 行交互逻辑已拆为 ES modules。
 *
 * 入口：frontend/index.html -> <script type="module" src="js/main.js">
 * 结构：frontend/js/store.js（共享状态与纯工具）
 *       frontend/js/api.js（API 封装）
 *       frontend/js/views/*.js（按域：chat / reading / pron / exam /
 *                                assessment / growth / review / feedback /
 *                                audio / word-popover / shadow / onboarding）
 *
 * 本文件刻意保留为空壳：git 历史与历史文档里的 frontend/app.js 指针仍然有效，
 * 但不再承载任何逻辑。请勿在此追加代码——新功能按 MASTER_PLAN.md 的文件边界
 * 写入 frontend/js/views/<feature>.js。
 */
