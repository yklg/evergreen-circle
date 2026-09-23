/**
 * 底图注记开关（需求 A）：全局单一真源，所有 LcMap 实例（地图页 / 对比页 A·B）同步翻转。
 *
 * 默认 **关** ⇒ 与改动前逐像素一致、零回归；既有契约测试（`bmapStyle.test.tsx`）不需改。
 * 持久化 key：`verda.mapNotes.v1`（'1'=开 / '0'=关）。
 */
import { createLocalBool } from '../lib/localBool'

export const useMapNotesStore = createLocalBool('verda.mapNotes.v1', false)
