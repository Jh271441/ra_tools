"""Review tag descriptions keyed by group and display name, including managed tags."""

REVIEW_TAG_DESCRIPTIONS = {
    # 场景环境
    ('environment', '施工/变更区域'): (
        "触发地点有施工围挡、临时改道或道路布局变化。",
        "Roadworks, a temporary diversion or a changed road layout are present at the trigger location.",
    ),
    ('environment', '道闸'): (
        "自车在闸杆附近通行；记录闸口环境，抬杆是否正常另看触发原因。",
        "The vehicle is at a barrier gate. Record the location here and assess the gate operation separately.",
    ),
    ('environment', '园区出入口'): (
        "触发位置在园区进出口，涵盖进出车流与道路交汇的位置。",
        "The trigger is at a site entrance or exit where site traffic joins the road.",
    ),
    ('environment', '其他'): (
        "触发位置不符合已有环境标签，可在评论里写明道路或场地类型。",
        "Use when no listed setting fits. Name the road or site type in a comment.",
    ),
    ('environment', '路口前'): (
        "路口前实线区域",
        "The solid-line approach to an intersection.",
    ),
    ('environment', '环岛'): (
        "触发位置在环岛入口、环道内或出口。",
        "The trigger is at a roundabout entrance, on the roundabout or at its exit.",
    ),
    ('environment', '禁停区前'): (
        "触发时自车位于禁停区入口之前；禁停约束是否导致卡住需另判。",
        "The vehicle is upstream of a keep-clear area. Assess separately whether that restriction caused the stop.",
    ),
    ('environment', '一般直行道路'): (
        "常规场景",
        "A typical straight-road setting.",
    ),
    ('environment', '路口内'): (
        "路口斑马线以及其围住的内部范围",
        "The intersection crosswalks and the area they enclose.",
    ),
    ('environment', '公交站'): (
        "公交站内, 或前后附近的区域.",
        "Within a bus stop or immediately before or after it.",
    ),
    ('environment', '匝道'): (
        "并入主道 / 从主道到辅路",
        "A ramp joining the main road or connecting it to a service road.",
    ),
    ('environment', '站点'): (
        "内部停车点(酒店, 等)",
        "A designated stopping point within a site, such as a hotel.",
    ),
    # 自车意图
    ('self_intent', '直行'): (
        "按触发时的目标路线，自车要沿道路继续向前。",
        "The intended route continues straight at the trigger.",
    ),
    ('self_intent', '左转'): (
        "按触发时的目标路线，自车接下来要向左转入另一条道路。",
        "The intended route turns left onto another road at the trigger.",
    ),
    ('self_intent', '右转'): (
        "按触发时的目标路线，自车接下来要向右转入另一条道路。",
        "The intended route turns right onto another road at the trigger.",
    ),
    ('self_intent', '掉头'): (
        "按触发时的目标路线，自车要调转方向，驶入反向车流。",
        "The intended route reverses direction to join traffic going the other way.",
    ),
    ('self_intent', '变道'): (
        "为继续目标路线，自车需要进入同向另一条车道。",
        "The vehicle needs to enter another lane in the same direction to follow its route.",
    ),
    ('self_intent', '泊车'): (
        "在不远处靠边泊车, 包括: 准备泊入, 泊入中, 泊入成功等待订单",
        "The vehicle is about to park at the curb, is parking, or has parked and is waiting for an order.",
    ),
    # 误触发原因
    ('false_trigger', '等灯'): (
        "触发时信号仍要求停车，自车在停止线或车流前正常等灯。",
        "The signal still requires a stop when RA triggers, so waiting for the light is appropriate.",
    ),
    ('false_trigger', '排队'): (
        "前车队列挡住目标路线，自车需要随队通行。例如要左转时，旁边直行车道空着也应等。",
        "A queue blocks the intended route. A vehicle waiting to turn left may need to stay in line even if the through lane is clear.",
    ),
    ('false_trigger', '让行'): (
        "来车、行人或骑行者正占用预定路径，自车在等安全空档再起步、转弯或变道。",
        "Traffic, a pedestrian or a rider conflicts with the intended path. The vehicle is waiting for a safe gap.",
    ),
    ('false_trigger', '掉头'): (
        "触发时自车正在正常掉头，因调整姿态或等待对向车流短暂停车。",
        "A U-turn is proceeding normally. The vehicle pauses to reposition or wait for opposing traffic.",
    ),
    ('false_trigger', '泊入'): (
        "触发时仍在泊入流程中，自车正调整位置或等待泊入点腾空。",
        "Parking is still in progress. The vehicle is positioning itself or waiting for the stopping point to clear.",
    ),
    ('false_trigger', '泊出'): (
        "触发时已有驶出泊位的轨迹，自车在等待汇入车流的安全空档。",
        "A pull-out path is already planned. The vehicle is waiting for a safe gap to merge.",
    ),
    ('false_trigger', '其他'): (
        "触发时无需 RA，但已有误触发标签均不适用。可在评论里写明等待或停车原因。",
        "RA was unnecessary at the trigger and no listed reason fits. Describe why the vehicle was waiting or stopped.",
    ),
    ('false_trigger', '人工误触发'): (
        "人工发起请求时，自车仍可正常通行或合理等待，当时无需脱困协助。",
        "A person requested RA while the vehicle could proceed normally or was appropriately waiting.",
    ),
    ('false_trigger', '园区抬杆'): (
        "等待抬杆, 没有其他通行办法",
        "The vehicle must wait for the barrier to rise. No alternative passage is available.",
    ),
    ('false_trigger', '短时跳变'): (
        "感知规划等跳变, 时间短, 虽影响效率, 但很快自行通行.",
        "A brief change in perception or planning slows the vehicle, but it soon proceeds on its own.",
    ),
    ('false_trigger', '非静止'): (
        "触发的时候非静止",
        "The vehicle was moving when the request was triggered.",
    ),
    # 应该触发的原因
    ('true_trigger', '未避障'): (
        "前方障碍挡住路线，旁边已有可行空间，但自车没有规划或完成绕行。",
        "An obstacle blocks the route. There is room to pass, but the vehicle has not planned or completed a path around it.",
    ),
    ('true_trigger', '距离近/窄距'): (
        "自车与周围车辆或障碍的间距过小，剩余空间限制通行。",
        "Clearance to nearby vehicles or obstacles is too tight for the vehicle to proceed.",
    ),
    ('true_trigger', '感知FP'): (
        "感知误报了障碍，自车因这个实际不存在的目标停车或无法前进。",
        "A falsely detected obstacle causes the vehicle to stop or blocks its path.",
    ),
    ('true_trigger', 'EOL'): (
        "当前车道或参考线走到可用末端，主系统接不出后续可行路径。",
        "The usable lane or reference line ends and the driving system cannot find a feasible continuation.",
    ),
    ('true_trigger', '地图变更'): (
        "现场道路或通行规则与地图不一致，主系统按原地图无法继续。",
        "The road layout or traffic controls differ from the map, preventing the vehicle from following its mapped route.",
    ),
    ('true_trigger', '红绿灯无灯坏'): (
        "路口信号灯缺失、故障或灯态不可用，自车无法确认放行而停住。",
        "The signal is absent, faulty or unreadable. The vehicle stops because it cannot establish permission to proceed.",
    ),
    ('true_trigger', '多余变道'): (
        "当前车道可继续目标路线，主系统却为非必要的变道停车或等待。",
        "The current lane serves the route, but the vehicle stops or waits for an unnecessary lane change.",
    ),
    ('true_trigger', '其他'): (
        "触发时确有通行困难，但已有原因标签均不适用。可在评论里写明卡住原因。",
        "The vehicle genuinely cannot proceed and no listed trigger reason fits. Describe what blocks progress.",
    ),
    ('true_trigger', 'ML规划异常'): (
        "ML轨迹, Backup Path, 等无法生成合理轨迹",
        "The ML trajectory or backup path fails to produce a feasible route.",
    ),
    ('true_trigger', '禁停区'): (
        "禁停区约束使自车提前停车或持续等待，触发时已有通过条件。",
        "A keep-clear restriction causes an early or prolonged stop even though the vehicle can clear the area.",
    ),
    ('true_trigger', '过度让行'): (
        "冲突目标已离开，或已有安全通行空档，自车仍持续等待。结合当时空档判断。",
        "The conflicting road user has cleared or a safe gap is available, yet the vehicle continues to yield.",
    ),
    ('true_trigger', '变道败'): (
        "path 不符合 routing 意图",
        "The planned path does not match the intended route.",
    ),
    ('true_trigger', '园区抬杆败'): (
        "进出园区需要抬杆, 但自车停住位置不佳, 需要调整",
        "The barrier must open for entry or exit, but the vehicle needs to reposition first.",
    ),
    ('true_trigger', '红绿灯polygon'): (
        "信号灯控制区域与自车路径相交，并实际限制通行；核对停车点与区域的位置。",
        "A signal-control polygon intersects the intended path and holds the vehicle. Check the stop position against the polygon.",
    ),
    ('true_trigger', '窄路会车'): (
        "狭窄路段有对向来车，双方交会时的横向空间限制了自车通行。",
        "Oncoming traffic on a narrow road leaves insufficient lateral clearance for the vehicles to pass.",
    ),
    ('true_trigger', 'keep clear'): (
        "自车停在 keep clear 停止线前；核对下游是否已有足够空间让整车通过。",
        "The vehicle waits at a keep-clear line. Check whether there is room beyond it for the whole vehicle.",
    ),
    ('true_trigger', '施工占道'): (
        "施工车辆、设备或围挡实际占用自车所需车道，压缩或堵住通行空间。",
        "Construction vehicles, equipment or barriers occupy the required lane and narrow or block the path.",
    ),
    ('true_trigger', '掉头半径小'): (
        "可用空间容不下当前掉头轨迹，轨迹碰到路缘或障碍，自车无法完成掉头。",
        "The planned U-turn does not fit the available space. Its path reaches the curb or an obstacle and the turn stalls.",
    ),
    # RA 协助方式与结果
    ('ra', 'SWAG'): (
        "SWAG 引导路径生效后，自车沿该路径起步脱困。核对生效与起步的先后。",
        "The vehicle starts along the active SWAG path and gets clear. Check that the path took effect before motion began.",
    ),
    ('ra', '左右绕行'): (
        "RA 的左绕行或右绕行指令生效，自车据此绕开阻挡。",
        "An RA left- or right-detour command takes effect and guides the vehicle around the blockage.",
    ),
    ('ra', 'Waypoint'): (
        "RA 画点生成引导路径，自车沿下发的点驶离卡住位置。",
        "RA supplies waypoints and the vehicle follows them out of the blocked position.",
    ),
    ('ra', '倒车'): (
        "RA 协助自车倒退，腾出调整姿态或重新驶出的空间。",
        "RA assists the vehicle in reversing to make room to reposition or pull away.",
    ),
    ('ra', '接管'): (
        "由人工接过车辆控制，实际完成起步或驶离。",
        "A person takes control of the vehicle and gets it moving or drives it clear.",
    ),
    ('ra', '红绿灯通行'): (
        "远程通行确认生效后，信号灯停车约束解除，自车随即驶离。",
        "Remote confirmation to proceed releases the signal-related stop and the vehicle moves off.",
    ),
    ('ra', '其他'): (
        "RA 的操作实际帮助自车驶离，但已有协助方式均不适用。可在评论里写明操作。",
        "An RA action helped the vehicle get clear and no listed method fits. Describe the action in a comment.",
    ),
    ('ra', '感知FP忽略'): (
        "忽略感知FP物体",
        "The false-positive object is ignored.",
    ),
    ('ra', '失败'): (
        "本次请求已尝试协助，仍未脱困；后续再次触发的结果另计。",
        "Assistance was attempted on this request, but the vehicle remained stuck. Judge a later request separately.",
    ),
    ('ra', 'out_of_scope'): (
        "现有 RA 手段无法处理，例如现场完全没有通行空间。是否应触发需另判。",
        "Available RA actions cannot resolve the situation, for example when no space is available. Assess the trigger separately.",
    ),
    ('ra', '蠕行'): (
        "RA 协助自车以极低速度小幅前挪，通过受限位置。核对前挪由哪一方发起。",
        "RA assists the vehicle in inching through a tight spot. Check who initiated the motion.",
    ),
    # 无需协助的驶离原因
    ('no_assist', '前车驶离'): (
        "挡路的前车先移开，通行空间恢复，自车随后自行起步。",
        "The blocking vehicle moves away first, opening space for the ego vehicle to start on its own.",
    ),
    ('no_assist', '主系统决策变化'): (
        "主系统自行改变决策后起步，例如从等待改为绕行，或重新规划路线。",
        "The driving system changes its own plan and moves off, for example by switching from waiting to a detour or rerouting.",
    ),
    ('no_assist', '感知FP变化'): (
        "原先误报的障碍消失或被修正，主系统随后自行恢复通行。",
        "A false detection clears or is corrected, allowing the driving system to resume without assistance.",
    ),
    ('no_assist', '其他'): (
        "自车无需协助便恢复通行，但已有驶离原因均不适用。可在评论里写明变化。",
        "The vehicle resumes without assistance and no listed cause fits. Describe what changed.",
    ),
}


def with_review_tag_description(item):
    """Keep the editable hint intact. Only translate reviewed wording."""
    pair = REVIEW_TAG_DESCRIPTIONS.get((item.get("group"), item.get("label")))
    if pair and not item.get("deleted") and (item.get("hint") or "").strip() in ("", pair[0]):
        return {**item, "description_zh": pair[0], "description_en": pair[1]}
    return item
