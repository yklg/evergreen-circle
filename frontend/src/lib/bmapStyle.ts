/**
 * 常青圈 · BMapGL 底图风格（C7 底图风格调适 · S2 低饱和浅灰，已确认）。
 *
 * 目标：真实百度底图融入项目浅色视觉——底色对齐现有画布 `#f9faf8`，
 * 道路/水系/建筑低饱和，POI 标注置灰，弱化与覆盖层（等时圈/POI Marker）的争色。
 * 通过 `map.setMapStyleV2({ styleJson: LC_MAP_STYLE_LIGHT })` 生效。
 *
 * 优先级：后端 `BAIDU_MAP_STYLE_ID`（百度控制台「个性化地图」发布的 styleId）优先；
 * 本内置模板仅作无 styleId 时的兜底（零配置即可用，LcMap 内已按此顺序应用）。
 */
export const LC_MAP_STYLE_LIGHT: Record<string, unknown>[] = [
  { featureType: 'land', elementType: 'geometry', stylers: { color: '#f9faf8' } },
  { featureType: 'water', elementType: 'geometry', stylers: { color: '#e2ecf3' } },
  { featureType: 'green', elementType: 'geometry', stylers: { color: '#e9efe6' } },
  { featureType: 'building', elementType: 'geometry', stylers: { color: '#f2f4f2' } },
  { featureType: 'road', elementType: 'geometry', stylers: { color: '#ffffff' } },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: { color: '#e6e9e7' } },
  { featureType: 'arterial', elementType: 'geometry', stylers: { color: '#ffffff' } },
  { featureType: 'arterial', elementType: 'geometry.stroke', stylers: { color: '#dfe4df' } },
  { featureType: 'highway', elementType: 'geometry', stylers: { color: '#ffffff' } },
  { featureType: 'highway', elementType: 'geometry.stroke', stylers: { color: '#d8ddd9' } },
  { featureType: 'poilabel', elementType: 'labels.text.fill', stylers: { color: '#a8b0a8' } },
  { featureType: 'poilabel', elementType: 'labels.icon', stylers: { visibility: 'off' } },
  { featureType: 'label', elementType: 'labels.text.fill', stylers: { color: '#a8b0a8' } },
]
