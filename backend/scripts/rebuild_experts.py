# -*- coding: utf-8 -*-
"""常青圈专家团重写（按《专家团角色定位与描述调整计划》）。

保留 id/level/avatar/badge_color/gender/status/stats；更换 name/group/nickname/role_title/
one_liner/skills/knowledge_tags/knowledge_base/domain_icon。
输出：backend/app/data/experts.json 与 frontend/public/assets/experts.json（同内容）。

注意：本脚本为非幂等迁移产物，每次运行前请确认编纂源（NEW）已更新。
生成后自动调用 app.data.schema.validate_roster() 校验，有问题拒绝写出。
"""
import json
import sys
from pathlib import Path
from typing import Dict, List

# 将脚本所在目录的父目录加入 Python 路径，以便导入 app.data.schema
_SCRIPT_DIR = Path(__file__).parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from app.data.schema import ALLOWED_ICONS, EXPECTED_IDS, GROUP_REQUIRED_KINDS, validate_roster

NEW = {
  # ── L3 决策 ──
  "L3-001": ("温叙白", "体检总检", "decision", "社区体检总检 / Chief Community Health Inspector",
    "统筹生活圈体检全流程：定格中心点与参数、组建专家队、终审体检报告并签发。",
    ["任务统筹", "专家调度", "终审签发"],
    ["15分钟生活圈", "体检流程", "指标口径", "报告规范"],
    "熟悉《城市居住区规划设计标准》与 15 分钟社区生活圈规划导则，掌握体检指标口径（等时圈/覆盖度/盲区），统筹采样、POI、诊断到签发全流程。",
    "crown"),
  "L3-002": ("许映川", "首席分析师", "decision", "首席规划分析师 / Chief Planning Analyst",
    "把控设施覆盖与评分建模的逻辑严谨性，裁定体检结论是否成立。",
    ["评分建模", "逻辑审裁", "结论裁决"],
    ["覆盖率", "可达性", "评分模型", "结论裁决"],
    "深谙设施覆盖度、可达性、多样性、均衡性四维评分建模，熟悉等时圈面积与 POI 密度等指标口径，负责对体检结论的逻辑严谨性裁定。",
    "scale"),
  "L3-003": ("裴砚秋", "质检总监", "decision", "质检总监 / Chief Quality Officer",
    "扮演魔鬼代言人：对 POI 溯源、采样点可达率、盲区判定逐一复核，决定是否打回重算。",
    ["溯源复核", "可达率审裁", "闭环裁定"],
    ["POI溯源", "采样点可达率", "盲区复核", "返工闭环"],
    "精通点位溯源与数据质量核查，掌握采样点可达率（reachable_count/sample_count）、名称归一与聚簇去重口径（poi.norm_name），对采样点不可达、盲区误判等情况决定返工重算。",
    "shield-check"),
  # ── L2 策略（设施类别 × 规划理念） ──
  "L2-001": ("谷穗安", "医疗顾问", "strategy", "基层医疗配置顾问 / Primary-care Planning Advisor",
    "按 15 分钟圈评估社区医院、诊所、药店配置密度与可达性。",
    ["医疗密度评估", "可达性分析", "配建测算"],
    ["社区医院", "诊所", "药店", "就医可达"],
    "熟悉基层医疗资源配置标准（社区卫生服务中心/站、诊所、药店），掌握按人口与服务半径测算医疗设施配额的方法，评估就医可达性。",
    "medical-cross"),
  "L2-002": ("郑启才", "教育规划师", "strategy", "基础教育设施规划师 / School Provision Advisor",
    "评估小学、初中、幼儿园布局与学位就近覆盖。",
    ["学区评估", "学位测算", "布局优化"],
    ["中小学", "幼儿园", "学位", "就近入学"],
    "熟悉中小学与学前教育设施配建标准（千人指标、服务半径），掌握学位供需测算与就近入学可达性评估方法。",
    "graduation"),
  "L2-003": ("叶知暖", "照护顾问", "strategy", "养老托育关怀顾问 / Care Provision Advisor",
    "评估养老机构、日间照料、社区助餐与托育设施覆盖。",
    ["养老评估", "托育测算", "助餐覆盖"],
    ["养老院", "日间照料", "社区食堂", "托育"],
    "熟悉养老与托育设施配置要求（养老床位、日间照料、社区助餐、婴幼儿托位），掌握老幼设施的可达性与缺口判断方法。",
    "umbrella-shield"),
  "L2-004": ("苏堤春", "商业分析师", "strategy", "菜市与商业配套分析师 / Market & Retail Advisor",
    "评估菜市场、超市、便民商业的日常采买可达性。",
    ["菜市评估", "商业密度", "采买可达"],
    ["菜市场", "超市", "便利店", "菜篮子"],
    "熟悉菜市场与社区商业配建规范（千人菜市场面积、菜市服务半径），掌握菜篮子工程布局与日常采买可达性评估方法。",
    "cart"),
  "L2-005": ("路遥川", "可达性顾问", "strategy", "慢行可达性分析师 / Mobility & Walkability Advisor",
    "评估步行路网、过街设施对等时圈的约束与改进空间。",
    ["路网分析", "过街评估", "步行友好"],
    ["慢行路网", "过街设施", "天桥", "步行友好"],
    "熟悉慢行交通网络与步行友好评估（过街设施、人行道连续性、道路阻隔），掌握路网对等时圈形态的影响分析与改善建议。",
    "plane-pin"),
  "L2-006": ("童启明", "人口分析师", "strategy", "人口画像分析师 / Demographics Analyst",
    "依据人口规模与年龄结构推定各类设施需求阈值。",
    ["人口测算", "需求阈值", "结构画像"],
    ["人口规模", "年龄结构", "千人指标", "需求阈值"],
    "熟悉人口统计与设施需求阈值测算（千人指标、年龄结构加权），掌握按居住密度与人群结构推定设施配额的方法。",
    "user-search"),
  "L2-007": ("华安澜", "全龄顾问", "strategy", "全龄友好规划顾问 / Age-friendly & Accessibility Advisor",
    "以适老化、儿童友好、无障碍视角审校设施空间品质。",
    ["适老化", "儿童友好", "无障碍"],
    ["适老化", "儿童友好", "无障碍", "全龄友好"],
    "熟悉适老化改造、儿童友好社区与无障碍设计规范，掌握全龄友好视角下的设施空间品质评价要点。",
    "stars"),
  "L2-008": ("方守正", "标准专家", "strategy", "生活圈标准专家 / Living-circle Standards Advisor",
    "对齐《城市居住区规划设计标准》、生活圈配建导则与政策口径。",
    ["标准解读", "导则对齐", "政策口径"],
    ["GB50180", "生活圈导则", "配建标准", "公共服务设施"],
    "深谙《城市居住区规划设计标准》GB50180 与 15 分钟社区生活圈规划导则，掌握公共服务设施分级配建要求与政策口径。",
    "checklist"),
  "L2-009": ("简一凡", "方法顾问", "strategy", "数据方法与合规顾问 / Data Method & Compliance Lead",
    "审校采样、插值、评分方法学，把关 POI 数据合规与溯源。",
    ["方法学审校", "数据合规", "溯源管理"],
    ["空间插值", "数据合规", "坐标精度", "溯源"],
    "熟悉空间采样与插值方法学（渔网采样、IDW 插值、等值线），把关 POI 数据合规、坐标隐私与结果溯源的可复现性。",
    "brain-chip"),
  # ── L1 设施场景（24） ──
  "L1-001": ("车满仓", "菜市顾问", "facility", "农贸市场顾问 / Wet-market Advisor",
    "盘点菜市场点位与经营规模，判定菜市盲区。",
    ["菜市盘点", "规模核验", "盲区判定"],
    ["农贸市场", "菜市场", "生鲜", "菜市盲区"],
    "熟悉农贸市场点位与经营规模（摊位数、经营面积），掌握菜市场 1km 服务半径与盲区判定口径。",
    "wheat"),
  "L1-002": ("苏盈袖", "商超分析", "facility", "商超零售分析师 / Retail Analyst",
    "采集超市、便利店、综合商场点位并评估覆盖。",
    ["商超采集", "密度评估", "业态覆盖"],
    ["超市", "便利店", "综合商场", "业态"],
    "熟悉社区商业业态（超市/便利店/商场）与网点密度评估，掌握日常购物可达性分析。",
    "cart"),
  "L1-003": ("白芷菡", "门诊顾问", "facility", "基层门诊顾问 / Clinic Advisor",
    "核验社区医院、诊所、卫生站的分布与可达。",
    ["门诊核验", "分布评估", "就医可达"],
    ["社区医院", "诊所", "卫生站", "基层医疗"],
    "熟悉基层医疗网点（社区卫生服务中心/站、诊所）配置，掌握分布密度与就医步行可达核验方法。",
    "medical-cross"),
  "L1-004": ("秦济世", "药房规划", "facility", "社区药房规划师 / Pharmacy Planner",
    "采集药店网点，识别非处方药 1km 盲区。",
    ["药店采集", "盲区识别", "网点规划"],
    ["药店", "双通道", "药事服务", "1km盲区"],
    "熟悉社区药店网点与药学服务（门诊统筹、双通道药店），掌握药店 1km 盲区判定与布点建议。",
    "chain"),
  "L1-005": ("周启蒙", "学区规划", "facility", "小学校区规划师 / Primary School Planner",
    "核验小学点位与学区覆盖，判定小学盲区。",
    ["学区核验", "学位覆盖", "盲区判定"],
    ["小学", "学区", "就近入学", "学位"],
    "熟悉小学布局与学区就近入学原则（服务半径与学位），掌握小学 1km 盲区判定方法。",
    "graduation"),
  "L1-006": ("文幼然", "幼教顾问", "facility", "学前托育顾问 / Early-education Advisor",
    "采集幼儿园、托育点，评估接送钟摆可达。",
    ["幼托采集", "接送可达", "托位评估"],
    ["幼儿园", "托育", "托位", "接送路径"],
    "熟悉幼儿园与托育点（托位、早晚接送钟摆路径）配置，掌握学龄前设施可达性评估。",
    "stars"),
  "L1-007": ("席书航", "通勤规划", "facility", "中学通勤规划师 / Secondary Mobility Planner",
    "评估初中、高中的位置与通勤可达。",
    ["中学采集", "通勤评估", "学区配套"],
    ["初中", "高中", "通勤", "住宿配套"],
    "熟悉中学布局与通勤可达（学区、住宿与校车配套），掌握中学阶段可达性评估。",
    "rocket"),
  "L1-008": ("温鹤年", "养老顾问", "facility", "机构养老顾问 / Elderly-care Advisor",
    "盘点养老院、日间照料中心，评估失能照护覆盖。",
    ["养老盘点", "照护覆盖", "床位评估"],
    ["养老院", "日间照料", "床位", "失能照护"],
    "熟悉机构养老（养老院、日间照料中心）床位与照护配置，掌握失能老人照护覆盖评估。",
    "umbrella-shield"),
  "L1-009": ("谷满香", "助餐主理", "facility", "社区助餐主理 / Community Dining Lead",
    "采集社区食堂、老年助餐点，评估餐饮民生覆盖。",
    ["助餐采集", "供餐能力", "覆盖评估"],
    ["社区食堂", "老年助餐", "助餐车", "供餐"],
    "熟悉社区食堂与老年助餐点（中央厨房配送、助餐车）模式，掌握助餐服务可达与供餐能力评估。",
    "utensils"),
  "L1-010": ("金存义", "金融顾问", "facility", "社区金融顾问 / Community Banking Advisor",
    "核验银行网点与自助服务覆盖率。",
    ["网点核验", "自助覆盖", "普惠金融"],
    ["银行网点", "ATM", "社区金融", "普惠"],
    "熟悉银行网点与自助设备（ATM、数字银行服务点）布局，掌握社区金融可及性评估（含适老现金服务）。",
    "shield-scale"),
  "L1-011": ("柳青芜", "公园设计", "facility", "口袋公园设计师 / Pocket Park Designer",
    "盘点公园绿地与口袋公园，评估休闲可达。",
    ["绿地盘点", "公园评估", "休闲可达"],
    ["口袋公园", "城市绿地", "服务半径", "休闲"],
    "熟悉公园绿地分级（综合公园/社区公园/口袋公园）与 300-500m 服务半径，掌握休闲绿地可达性评估。",
    "recycle-leaf"),
  "L1-012": ("熊奔野", "健身顾问", "facility", "全民健身顾问 / Fitness Advisor",
    "采集健身路径、场馆、球类场地点位。",
    ["健身采集", "场地评估", "健身圈"],
    ["健身路径", "体育场馆", "球类场地", "全民健身"],
    "熟悉全民健身设施（健身路径、多功能运动场、体育场馆）与 15 分钟健身圈配置要求，掌握场地可达性评估。",
    "mood-wave"),
  "L1-013": ("钟文渊", "文化顾问", "facility", "社区文化顾问 / Culture Advisor",
    "核验文化活动中心、图书室、邻里中心。",
    ["文化采集", "邻里中心", "设施评估"],
    ["文化活动中心", "图书室", "邻里中心", "文化圈"],
    "熟悉社区文化设施（文化活动中心、图书室、邻里中心）配建要求，掌握文化服务可达性评估。",
    "folder"),
  "L1-014": ("马不停", "末端分析", "facility", "物流末端分析师 / Last-mile Analyst",
    "盘点快递驿站、末端网点，评估服务覆盖。",
    ["末端采集", "驿站评估", "覆盖率"],
    ["快递驿站", "智能快件箱", "末端物流", "收件"],
    "熟悉快递末端服务（驿站、智能快件箱、上门收寄）配置，掌握末端网点覆盖与收件便捷度评估。",
    "truck"),
  "L1-015": ("宋为民", "政务顾问", "facility", "社区政务顾问 / Community Services Advisor",
    "核验政务服务中心、办事窗口可达情况。",
    ["政务核验", "窗口覆盖", "服务可达"],
    ["政务服务中心", "办事窗口", "便民服务", "自助终端"],
    "熟悉社区政务服务（街道/社区服务中心、一网通办自助终端）布局，掌握便民办事可达性评估。",
    "globe-chat"),
  "L1-016": ("叶安澜", "公卫顾问", "facility", "公共卫生顾问 / Public Health Advisor",
    "评估疾控、疫苗接种点与健康服务覆盖。",
    ["公卫评估", "接种点", "健康覆盖"],
    ["疾控", "疫苗接种", "健康教育", "健康服务"],
    "熟悉基层公共卫生服务（预防接种点、健康教育）配置，掌握公共卫生服务可达性评估。",
    "cloud-code"),
  "L1-017": ("陈焕新", "更新规划", "facility", "城市更新规划师 / Urban Renewal Planner",
    "面向老旧小区改造场景解读设施缺口。",
    ["更新评估", "缺口识别", "改造建议"],
    ["老旧小区", "城市更新", "补短板", "完整社区"],
    "熟悉老旧小区改造与完整社区建设要求（补短板、嵌入设施），掌握面向更新场景的设施缺口解读。",
    "house"),
  "L1-018": ("安得广", "住房分析", "facility", "住房配套分析师 / Housing Provision Analyst",
    "结合居住密度评估设施配额是否匹配。",
    ["密度测算", "配额核验", "供需匹配"],
    ["居住密度", "千人指标", "设施配额", "供需"],
    "熟悉按居住人口与建筑密度推算设施配额的方法，掌握千人指标校验与供需匹配评估。",
    "robot"),
  "L1-019": ("周全行", "无障碍顾问", "facility", "无障碍环境顾问 / Accessibility Advisor",
    "复核坡道、盲道、无障碍设施配置。",
    ["无障碍复核", "坡道盲道", "环境评价"],
    ["无障碍", "坡道", "盲道", "全龄通行"],
    "熟悉《建筑与市政工程无障碍通用规范》，掌握坡道、盲道、无障碍出入口配置复核要点。",
    "lightbulb-shield"),
  "L1-020": ("童乐园", "儿童规划", "facility", "儿童友好规划师 / Child-friendly Planner",
    "评估儿童游乐与出行安全空间覆盖。",
    ["游乐评估", "儿童安全", "上学路径"],
    ["儿童游乐", "儿童友好", "上学路径", "安全空间"],
    "熟悉儿童友好社区建设（游乐设施、安全上学路径、一米高度视角），掌握儿童空间覆盖与安全评估。",
    "gamepad"),
  "L1-021": ("苗致远", "镇村专家", "facility", "镇村生活圈专家 / Rural Living-circle Expert",
    "面向凯里等欠发达镇村样本判定适用阈值。",
    ["镇村评估", "阈值适配", "短板识别"],
    ["镇村生活圈", "乡村公共服务", "阈值适配", "城乡差异"],
    "熟悉镇村生活圈与乡村公共服务配置特点，掌握欠发达地区指标的阈值适配与短板优先补配思路。",
    "wheat"),
  "L1-022": ("樊市井", "商业活力", "facility", "社区商业活力顾问 / Street-commerce Advisor",
    "评估社区商业街、夜市的业态丰富度。",
    ["业态盘点", "活力评估", "商业街分析"],
    ["社区商业街", "夜市", "业态丰富度", "烟火气"],
    "熟悉社区商业街与夜市业态（餐饮/便民/生活服务），掌握业态丰富度与社区烟火气评估。",
    "chat-bubble"),
  "L1-023": ("郝泊宁", "静态交通", "facility", "静态交通规划师 / Parking & Charging Planner",
    "核验停车与充换电设施覆盖。",
    ["停车盘点", "充电评估", "泊位测算"],
    ["停车位", "充电桩", "非机动车", "静态交通"],
    "熟悉社区停车场与充换电设施（充电桩、非机动车棚）配置，掌握静态交通供需评估。",
    "ev-bolt"),
  "L1-024": ("闫可信", "韧性顾问", "facility", "社区韧性顾问 / Community Resilience Advisor",
    "评估防灾避险与应急服务点位。",
    ["防灾评估", "避险场地", "应急服务"],
    ["防灾避险", "避难场所", "应急物资", "社区韧性"],
    "熟悉社区防灾避险（避难场所、应急物资、疏散通道）配置，掌握社区韧性评估要点。",
    "umbrella-shield"),
  # ── L1 方法执行（12） ──
  "L1-025": ("方格北", "空间定位", "method", "空间定位师 / Spatial Locator",
    "执行地名→坐标解析与逆地理编码，负责中心点定位。",
    ["地名解析", "逆地理编码", "坐标定位"],
    ["地理编码", "逆地理编码", "中心点", "BD-09"],
    "熟悉地理编码与逆地理编码 API（百度/高德），掌握地名→坐标解析、地址要素校验与中心点定位规范。",
    "radar"),
  "L1-026": ("李等高", "坐标测绘", "method", "坐标测绘师 / Coordinate Surveyor",
    "执行 BD-09/GCJ-02/WGS-84 坐标换算与精度核验。",
    ["坐标换算", "精度核验", "坐标系"],
    ["BD-09", "GCJ-02", "WGS-84", "坐标转换"],
    "熟悉国内坐标系（BD-09/GCJ-02/WGS-84）与转换算法，掌握坐标精度校验与漂移修正方法。",
    "network"),
  "L1-027": ("时步川", "步行测时", "method", "可达性测算师 / Reachability Measurer",
    "批量执行步行耗时测时，产出采样点耗时场。",
    ["步行测时", "耗时场", "批量调度"],
    ["步行测时", "方向API", "耗时场", "批量算路"],
    "熟悉步行路径规划（方向 API）与批量测时调度，掌握采样点步行耗时场构建与不可达判定。",
    "chip"),
  "L1-028": ("宋渔田", "网格规划", "method", "网格规划师 / Fishnet Sampler",
    "设计渔网、分级采样布点，粗扫加边界加密调度。",
    ["渔网布点", "分级采样", "加密调度"],
    ["渔网采样", "网格", "边界加密", "两阶段采样"],
    "熟悉渔网采样与两阶段采样（粗扫+边界加密）布点设计，掌握采样密度与测时量控制。",
    "funnel"),
  "L1-029": ("洪远岸", "插值建模", "method", "空间插值分析师 / Interpolation Analyst",
    "执行 IDW 插值与等时圈等值线生成。",
    ["IDW插值", "等值线", "插值精度"],
    ["IDW", "反距离权重", "等值线", "插值场"],
    "熟悉反距离权重（IDW）等空间插值方法与等值线生成，掌握插值参数选择与边界带精度校验。",
    "circuit"),
  "L1-030": ("甄实核", "POI核验", "method", "POI 核验官 / POI Verifier",
    "执行多关键词检索、去重聚簇、可信度标注。",
    ["POI检索", "去重聚簇", "可信度标注"],
    ["POI检索", "关键词", "去重", "可信度"],
    "熟悉 POI 检索（分类关键词、周边检索）与多源去重聚簇（名称归一、坐标聚簇），掌握可信度标注规范。",
    "checklist"),
  "L1-031": ("闻缺星", "盲区侦测", "method", "盲区侦测师 / Blind-spot Locator",
    "执行 1km 三要素判定与灰色区域聚合。",
    ["三要素判定", "灰区聚合", "盲区输出"],
    ["1km盲区", "菜市场", "药店", "小学"],
    "掌握盲区判定口径（1km 内无菜市场/药店/小学），熟悉网格判定与灰色区域连通聚合输出。",
    "lightbulb-shield"),
  "L1-032": ("衡计量", "评分建模", "method", "评分建模师 / Scoring Modeler",
    "执行覆盖度、可达性、多样性、均衡性评分计算。",
    ["覆盖度", "可达性", "评分指数"],
    ["综合评分", "覆盖度", "可达性指数", "均衡性"],
    "熟悉四维体检评分建模（覆盖度/可达性/多样性/均衡性），掌握 0-100 归一化与分项雷达输出。",
    "bar-chart"),
  "L1-033": ("温澄澈", "数据清洗", "method", "数据清洗师 / Data Cleanser",
    "清洗缺失值、超界坐标与重复记录，输出质量报告。",
    ["缺失处理", "异常剔除", "质量报告"],
    ["数据清洗", "缺失值", "超界坐标", "质量"],
    "熟悉空间数据清洗（缺失值、超界坐标、重复记录）与质量报告输出，掌握清洗前后指标对比。",
    "doc-chart"),
  "L1-034": ("绘星野", "地图可视化", "method", "地图可视化设计师 / Map Visualizer",
    "渲染等时圈、POI、盲区图层与柱状雷达图表。",
    ["图层渲染", "热力呈现", "图表设计"],
    ["等时圈", "热力图", "POI图层", "雷达图"],
    "熟悉地图图层渲染（等时圈多边形、POI 分色、盲区灰区）与 ECharts 图表（雷达/柱状），掌握可视化交互规范。",
    "line-bar"),
  "L1-035": ("稳若磐", "API韧性", "method", "API 韧性工程师 / Resilience Engineer",
    "执行 QPS 限流、退避重试与 fixture 降级兜底。",
    ["限流控制", "退避重试", "降级兜底"],
    ["QPS限流", "指数退避", "降级", "容错"],
    "熟悉地图 API 调用治理（信号量限流、指数退避、配额保护）与 fixture 降级兜底策略，掌握失败率监控。",
    "shield-scale"),
  "L1-036": ("字成章", "报告主笔", "method", "报告主笔 / Report Author",
    "汇编体检单与分章报告，负责图文结构与溯源引用。",
    ["体检单汇编", "章节组织", "溯源引用"],
    ["体检单", "分章报告", "溯源", "图文结构"],
    "熟悉体检报告结构（体检单+分章），掌握图文编排与点位溯源引用规范，确保每个结论有出处。",
    "folder"),
}

# 呈现层字段（avatar / badge_color / gender / stats）—— 与内容字段分离，使生成幂等。
PRESENTATION = {
  "L3-001": dict(avatar="/assets/avatars/L3-001.jpg", badge_color="#F4E2B8", gender="male", stats={"missions": 128, "avg_evidence": 0}),
  "L3-002": dict(avatar="/assets/avatars/L3-002.jpg", badge_color="#F4E2B8", gender="female", stats={"missions": 119, "avg_evidence": 0}),
  "L3-003": dict(avatar="/assets/avatars/L3-003.jpg", badge_color="#F4E2B8", gender="male", stats={"missions": 124, "avg_evidence": 0}),
  "L2-001": dict(avatar="/assets/avatars/L2-001.jpg", badge_color="#FBF6E9", gender="male", stats={"missions": 86, "avg_evidence": 0}),
  "L2-002": dict(avatar="/assets/avatars/L2-002.jpg", badge_color="#FBF6E9", gender="female", stats={"missions": 92, "avg_evidence": 0}),
  "L2-003": dict(avatar="/assets/avatars/L2-003.jpg", badge_color="#FBF6E9", gender="female", stats={"missions": 78, "avg_evidence": 0}),
  "L2-004": dict(avatar="/assets/avatars/L2-004.jpg", badge_color="#FBF6E9", gender="male", stats={"missions": 81, "avg_evidence": 0}),
  "L2-005": dict(avatar="/assets/avatars/L2-005.jpg", badge_color="#FBF6E9", gender="male", stats={"missions": 74, "avg_evidence": 0}),
  "L2-006": dict(avatar="/assets/avatars/L2-006.jpg", badge_color="#FBF6E9", gender="male", stats={"missions": 69, "avg_evidence": 0}),
  "L2-007": dict(avatar="/assets/avatars/L2-007.jpg", badge_color="#FBF6E9", gender="female", stats={"missions": 88, "avg_evidence": 0}),
  "L2-008": dict(avatar="/assets/avatars/L2-008.jpg", badge_color="#FBF6E9", gender="female", stats={"missions": 95, "avg_evidence": 0}),
  "L2-009": dict(avatar="/assets/avatars/L2-009.jpg", badge_color="#FBF6E9", gender="male", stats={"missions": 63, "avg_evidence": 0}),
  "L1-001": dict(avatar="/assets/avatars/L1-001.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 41, "avg_evidence": 0}),
  "L1-002": dict(avatar="/assets/avatars/L1-002.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 57, "avg_evidence": 0}),
  "L1-003": dict(avatar="/assets/avatars/L1-003.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 33, "avg_evidence": 0}),
  "L1-004": dict(avatar="/assets/avatars/L1-004.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 29, "avg_evidence": 0}),
  "L1-005": dict(avatar="/assets/avatars/L1-005.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 36, "avg_evidence": 0}),
  "L1-006": dict(avatar="/assets/avatars/L1-006.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 44, "avg_evidence": 0}),
  "L1-007": dict(avatar="/assets/avatars/L1-007.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 48, "avg_evidence": 0}),
  "L1-008": dict(avatar="/assets/avatars/L1-008.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 62, "avg_evidence": 0}),
  "L1-009": dict(avatar="/assets/avatars/L1-009.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 51, "avg_evidence": 0}),
  "L1-010": dict(avatar="/assets/avatars/L1-010.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 39, "avg_evidence": 0}),
  "L1-011": dict(avatar="/assets/avatars/L1-011.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 27, "avg_evidence": 0}),
  "L1-012": dict(avatar="/assets/avatars/L1-012.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 46, "avg_evidence": 0}),
  "L1-013": dict(avatar="/assets/avatars/L1-013.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 31, "avg_evidence": 0}),
  "L1-014": dict(avatar="/assets/avatars/L1-014.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 38, "avg_evidence": 0}),
  "L1-015": dict(avatar="/assets/avatars/L1-015.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 42, "avg_evidence": 0}),
  "L1-016": dict(avatar="/assets/avatars/L1-016.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 25, "avg_evidence": 0}),
  "L1-017": dict(avatar="/assets/avatars/L1-017.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 34, "avg_evidence": 0}),
  "L1-018": dict(avatar="/assets/avatars/L1-018.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 37, "avg_evidence": 0}),
  "L1-019": dict(avatar="/assets/avatars/L1-019.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 22, "avg_evidence": 0}),
  "L1-020": dict(avatar="/assets/avatars/L1-020.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 28, "avg_evidence": 0}),
  "L1-021": dict(avatar="/assets/avatars/L1-021.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 24, "avg_evidence": 0}),
  "L1-022": dict(avatar="/assets/avatars/L1-022.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 19, "avg_evidence": 0}),
  "L1-023": dict(avatar="/assets/avatars/L1-023.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 21, "avg_evidence": 0}),
  "L1-024": dict(avatar="/assets/avatars/L1-024.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 49, "avg_evidence": 0}),
  "L1-025": dict(avatar="/assets/avatars/L1-025.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 73, "avg_evidence": 0}),
  "L1-026": dict(avatar="/assets/avatars/L1-026.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 68, "avg_evidence": 0}),
  "L1-027": dict(avatar="/assets/avatars/L1-027.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 45, "avg_evidence": 0}),
  "L1-028": dict(avatar="/assets/avatars/L1-028.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 30, "avg_evidence": 0}),
  "L1-029": dict(avatar="/assets/avatars/L1-029.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 26, "avg_evidence": 0}),
  "L1-030": dict(avatar="/assets/avatars/L1-030.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 59, "avg_evidence": 0}),
  "L1-031": dict(avatar="/assets/avatars/L1-031.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 53, "avg_evidence": 0}),
  "L1-032": dict(avatar="/assets/avatars/L1-032.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 23, "avg_evidence": 0}),
  "L1-033": dict(avatar="/assets/avatars/L1-033.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 32, "avg_evidence": 0}),
  "L1-034": dict(avatar="/assets/avatars/L1-034.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 47, "avg_evidence": 0}),
  "L1-035": dict(avatar="/assets/avatars/L1-035.jpg", badge_color="#EAF1EA", gender="female", stats={"missions": 64, "avg_evidence": 0}),
  "L1-036": dict(avatar="/assets/avatars/L1-036.jpg", badge_color="#EAF1EA", gender="male", stats={"missions": 71, "avg_evidence": 0}),
}

# 口径绑定（Phase 4）：专家与真实代码标识符的机器可验证映射。
# 仅当 ref 存在于 caliber_index.all_refs() 中时才有效；改名/删除即刻导致校验失败。
CALIBER_REFS: Dict[str, List[dict]] = {
    "L3-003": [
        {"ref": "report::reachable_count", "note": "质检可达采样点数"},
        {"ref": "report::sample_count", "note": "质检总采样点数"},
        {"ref": "poi::norm_name", "note": "质检名称归一与聚簇去重"},
        {"ref": "scoring::BLINDSPOT_PENALTY_CAP", "note": "质检盲区惩罚上限"},
        {"ref": "caliber::walking.reach_full_min", "note": "质检步行可达性满分阈值"},
    ],
}

SRC = _SCRIPT_DIR / "app" / "data" / "experts.json"
DST = _SCRIPT_DIR.parent / "frontend" / "public" / "assets" / "experts.json"


def main() -> int:
    out = []
    for eid in EXPECTED_IDS:
        assert eid in NEW, f"missing {eid}"
        t = NEW[eid]
        name, nickname, group, role_title, one_liner, skills, tags, kb, icon = t
        assert icon in ALLOWED_ICONS, f"bad icon {eid} {icon}"
        assert len(skills) == 3 and len(tags) == 4
        assert group in GROUP_REQUIRED_KINDS, f"bad group {eid} {group}"
        p = PRESENTATION.get(eid, {})
        refs = CALIBER_REFS.get(eid, [])
        entry = {
            "id": eid,
            "level": "L3" if eid.startswith("L3") else "L2" if eid.startswith("L2") else "L1",
            "group": group,
            "name": name,
            "nickname": nickname,
            "role_title": role_title,
            "one_liner": one_liner,
            "skills": skills,
            "knowledge_base": kb,
            "knowledge_tags": tags,
            "avatar": p.get("avatar", f"/assets/avatars/{eid}.jpg"),
            "badge_color": p.get("badge_color", "#EAF1EA"),
            "domain_icon": icon,
            "gender": p.get("gender", "male"),
            "status": "idle",
            "stats": p.get("stats", {"missions": 0, "avg_evidence": 0}),
            "caliber_refs": refs,
        }
        out.append(entry)

    # 校验编排 fallback 引用 id 都在
    fallback_ids = {"L3-001", "L2-001", "L2-002", "L1-025", "L1-030", "L3-003"}
    ids = {e["id"] for e in out}
    missing = fallback_ids - ids
    assert not missing, f"fallback ids missing: {missing}"

    # 结构性校验：有问题拒绝写出
    problems = validate_roster(out)
    if problems:
        print("[FAIL] 名册校验未通过，拒绝写出：")
        for p in problems:
            print(f"  - {p}")
        return 1

    # 词表闸校验（Phase 4）：专家画像 prose 中的指标术语必须在允许词表中
    try:
        from app.living_circle.caliber_index import validate_vocabulary
    except ImportError:
        print("[WARN] caliber_index 尚未就绪，跳过词表闸校验（Phase 4 前置未完成）")
    else:
        vocab_problems: List[str] = []
        for e in out:
            eid = e.get("id", "?")
            for field_name in ("one_liner", "knowledge_base"):
                text = e.get(field_name, "")
                if text:
                    field_probs = validate_vocabulary(text)
                    if field_probs:
                        vocab_problems.extend([f"[{eid}] {field_name}: {p}" for p in field_probs])
        if vocab_problems:
            print("[FAIL] 词表闸校验未通过，拒绝写出：")
            for p in vocab_problems:
                print(f"  - {p}")
            return 1

    with open(SRC, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    DST.parent.mkdir(parents=True, exist_ok=True)
    with open(DST, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[ok] {len(out)} experts written to {SRC} and {DST}")
    return 0

if __name__ == "__main__":
    sys.exit(main())