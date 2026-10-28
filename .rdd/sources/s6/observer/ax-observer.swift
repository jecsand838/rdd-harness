import Foundation
import ApplicationServices
import Dispatch
import Darwin
import AppKit
import CryptoKit
func now()->UInt64{DispatchTime.now().uptimeNanoseconds}
var deltas:[UInt64]=[];var previous=now();for _ in 0..<10000{let current=now();if current>previous{deltas.append(current-previous)};previous=current}
var result:[String:Any] = ["trusted":AXIsProcessTrusted(),"clock":"DispatchTime.uptimeNanoseconds","clock_unit":"ns","minimum_observed_positive_delta_ns":deltas.min() ?? 0,"observed_clock_samples":deltas.count,"ui_actions_requested":false,"observer_bundle_identifier":Bundle.main.bundleIdentifier ?? "unbundled"]
func emit(_ data:[String:Any]){let raw=try! JSONSerialization.data(withJSONObject:data,options:[.prettyPrinted,.sortedKeys]);print(String(data:raw,encoding:.utf8)!)}
func matchingWindowIndices(_ descriptions:[[String:Any]])->[Int]{descriptions.enumerated().compactMap{ index,item in
 ((item["title"] as? String)=="RDD Qualification Carrier" && (item["role"] as? String)=="AXWindow" && (item["subrole"] as? String)=="AXStandardWindow") ? index:nil
}}
if CommandLine.arguments.count==2 && CommandLine.arguments[1]=="--selector-selftest" {
 let auxiliary:[String:Any]=["title":"Window","role":"AXWindow","subrole":"AXUnknown","width":66,"height":20]
 let carrier:[String:Any]=["title":"RDD Qualification Carrier","role":"AXWindow","subrole":"AXStandardWindow"]
 assert(matchingWindowIndices([auxiliary,carrier]) == [1])
 assert(matchingWindowIndices([auxiliary]).isEmpty)
 assert(matchingWindowIndices([carrier,carrier]).count == 2)
 assert(matchingWindowIndices([["title":"Other","role":"AXWindow","subrole":"AXStandardWindow"]]).isEmpty)
 assert(matchingWindowIndices([["title":"RDD Qualification Carrier","role":"AXGroup","subrole":"AXStandardWindow"]]).isEmpty)
 emit(["selector_predicate_selftest":"pass","cases":5,"scope":"pure descriptor predicate, not actual AX qualification"]);exit(0)
}

guard CommandLine.arguments.count==3 && CommandLine.arguments[1]=="--carrier-ui" else{emit(result);exit(0)}
result["ui_actions_requested"]=true
guard AXIsProcessTrusted() else{result["error"]="accessibility_not_authorized";emit(result);exit(2)}
guard let pid=pid_t(CommandLine.arguments[2]),let target=NSRunningApplication(processIdentifier:pid),let url=target.executableURL else{result["error"]="target_identity_unavailable";emit(result);exit(7)}
let expectedPath="/Users/connorsanders/Applications/RDD Qualification Carrier-R20261028T021552Z-CSP.app/Contents/MacOS/qualification-carrier"
let expectedHash="6f7bf88dd53153287ae2c137694ab1b7c0c91193bca9b4f9fae63946b4d35bb9"
let observedHash=(try? Data(contentsOf:url)).map{SHA256.hash(data:$0).map{String(format:"%02x",$0)}.joined()} ?? "unreadable"
result["target_pid"]=pid;result["target_path"]=url.path;result["target_bundle_identifier"]=target.bundleIdentifier ?? "absent";result["target_sha256"]=observedHash
let observerID="com.rdd.qualification.axobserver.r20261028.v6"
guard Bundle.main.bundleIdentifier==observerID && target.bundleIdentifier=="com.rdd.qualification.r20261028" && url.path==expectedPath && observedHash==expectedHash else{result["error"]="exact_carrier_identity_mismatch";emit(result);exit(8)}
let app=AXUIElementCreateApplication(pid);AXUIElementSetMessagingTimeout(app,0.1)
func attr(_ element:AXUIElement,_ key:String)->CFTypeRef?{var value:CFTypeRef?;let status=AXUIElementCopyAttributeValue(element,key as CFString,&value);return status == .success ? value:nil}
func children(_ e:AXUIElement)->[AXUIElement]{attr(e,kAXChildrenAttribute) as? [AXUIElement] ?? []}
func walk(_ e:AXUIElement)->[AXUIElement]{var stack:[(AXUIElement,Int)]=[(e,0)];var all:[AXUIElement]=[];while let (item,depth)=stack.popLast(){all.append(item);if all.count>=2000{break};if depth<20{for child in children(item){stack.append((child,depth+1))}}};return all}
func strings(_ items:[AXUIElement])->[String]{items.flatMap { e in [kAXValueAttribute,kAXTitleAttribute,kAXDescriptionAttribute].compactMap{attr(e,$0) as? String} }}
guard let windows=attr(app,kAXWindowsAttribute) as? [AXUIElement] else{result["error"]="no_windows_attribute";emit(result);exit(3)}
func pointSize(_ element:AXUIElement)->[String:Double]?{guard let v=attr(element,kAXSizeAttribute),CFGetTypeID(v)==AXValueGetTypeID() else{return nil};var s=CGSize.zero;guard AXValueGetValue(v as! AXValue,.cgSize,&s) else{return nil};return ["width":s.width,"height":s.height]}
func pointPosition(_ element:AXUIElement)->[String:Double]?{guard let v=attr(element,kAXPositionAttribute),CFGetTypeID(v)==AXValueGetTypeID() else{return nil};var s=CGPoint.zero;guard AXValueGetValue(v as! AXValue,.cgPoint,&s) else{return nil};return ["x":s.x,"y":s.y]}
let descriptions:[[String:Any]]=windows.enumerated().map{index,window in
 var row:[String:Any]=["index":index]
 for (field,key) in [("title",kAXTitleAttribute),("role",kAXRoleAttribute),("subrole",kAXSubroleAttribute),("identifier",kAXIdentifierAttribute)]{row[field]=(attr(window,key) as? String) ?? "absent"}
 if let size=pointSize(window){row["size_points"]=size};if let position=pointPosition(window){row["position_points"]=position};return row
}
let matches=matchingWindowIndices(descriptions);result["enumerated_windows"]=descriptions;result["matching_window_indices"]=matches;result["window_selector"]="exact title RDD Qualification Carrier; role AXWindow; subrole AXStandardWindow; require exactly one"
guard matches.count==1 else{result["error"]=matches.isEmpty ? "named_standard_carrier_window_missing":"named_standard_carrier_window_ambiguous";emit(result);exit(matches.isEmpty ? 9:10)}
let window=windows[matches[0]];result["selected_window_index"]=matches[0]
var requestedPosition=CGPoint(x:16,y:40);let positionValue=AXValueCreate(.cgPoint,&requestedPosition)!;let setPosition=AXUIElementSetAttributeValue(window,kAXPositionAttribute as CFString,positionValue);result["set_position_status"]=setPosition.rawValue;result["requested_position_points"]=["x":16,"y":40];if let position=pointPosition(window){result["position_readback_points"]=position};guard setPosition == .success else{result["error"]="carrier_position_preparation_failed";emit(result);exit(11)}
let positionStarted=now();var positionStable=0;var positionSamples:[[String:Any]]=[]
while now()-positionStarted<3_000_000_000 {let current=pointPosition(window);var sample:[String:Any]=["observed_ns":now()];if let current=current{sample["position_points"]=current};positionSamples.append(sample);if current?["x"]==16 && current?["y"]==40{positionStable += 1}else{positionStable=0};if positionStable>=3{break};usleep(20000)}
result["position_preparation_samples"]=positionSamples;result["stable_position_samples"]=positionStable;guard positionStable>=3 else{result["error"]="exact_position_not_settled_before_resize";emit(result);exit(11)}
var desired=CGSize(width:1280,height:720);let sizeValue=AXValueCreate(.cgSize,&desired)!
let axTopOrigin=NSScreen.screens.first?.frame.maxY ?? 0
let visibleFrames=NSScreen.screens.map{screen -> CGRect in let r=screen.visibleFrame;return CGRect(x:r.minX,y:axTopOrigin-r.maxY,width:r.width,height:r.height)}
result["visible_screen_bounds_ax_points"]=visibleFrames.map{["x":$0.minX,"y":$0.minY,"width":$0.width,"height":$0.height]};result["final_position_condition"]="stable and full window frame inside one observed visible screen; window-manager reposition allowed"
let geometryStarted=now();let setSize=AXUIElementSetAttributeValue(window,kAXSizeAttribute as CFString,sizeValue);result["set_size_status"]=setSize.rawValue
var actual=CGSize.zero;var stableSamples=0;var geometrySamples:[[String:Any]]=[];var previousSafePosition:[String:Double]?=nil
while now()-geometryStarted<3_000_000_000 {
 if let value=pointSize(window){actual=CGSize(width:value["width"]!,height:value["height"]!)}
 var sample:[String:Any]=["observed_ns":now(),"width":actual.width,"height":actual.height]
 if let position=pointPosition(window){sample["position_points"]=position};geometrySamples.append(sample)
 let safePosition=pointPosition(window);var withinVisible=false;if let position=safePosition{let frame=CGRect(x:position["x"]!,y:position["y"]!,width:actual.width,height:actual.height);withinVisible=visibleFrames.contains{$0.contains(frame)}}
 if actual.width==1280 && actual.height==720 && withinVisible {stableSamples = safePosition==previousSafePosition ? stableSamples+1:1}else{stableSamples=0};previousSafePosition=safePosition
 if stableSamples>=3{break};usleep(20000)
}
result["actual_window_size_points"]=["width":actual.width,"height":actual.height];result["geometry_samples"]=geometrySamples;result["stable_geometry_samples"]=stableSamples;result["geometry_poll_sleep_us"]=20000;result["geometry_started_ns"]=geometryStarted;result["geometry_finished_ns"]=now()
guard setSize == .success && actual.width==1280 && actual.height==720 && stableSamples>=3 else{result["error"]="exact_geometry_not_settled_before_action";emit(result);exit(6)}
let initial=walk(window);let initialText=strings(initial);result["initial_text"]=initialText
if let web=initial.first(where:{(attr($0,kAXRoleAttribute) as? String)=="AXWebArea"}),let value=attr(web,kAXSizeAttribute){var webSize=CGSize.zero;AXValueGetValue(value as! AXValue,.cgSize,&webSize);result["web_area_size_points"]=["width":webSize.width,"height":webSize.height]}
result["window_size_semantics"]="AX window frame points; WebArea content points recorded separately when exposed"
let buttons=initial.filter{(attr($0,kAXRoleAttribute) as? String)==kAXButtonRole}
guard let button=buttons.first(where:{strings([$0]).contains("Persist generated API probe")}) else{result["error"]="probe_button_absent";emit(result);exit(4)}
guard initialText.contains(where:{$0.contains("READY last=probe-20261028-R5")}) && !initialText.contains(where:{$0.contains("COMMITTED probe-20261028-R5")}) else{result["error"]="stale_result_precondition";emit(result);exit(5)}
let preconditionChecked=now();result["precondition_observed_absent_ns"]=preconditionChecked;let started=now();let status=AXUIElementPerformAction(button,kAXPressAction as CFString);let returned=now();var lastAbsent=preconditionChecked;var detected:UInt64?=nil;var polls=0;var observed:[String]=[]
while now()-started<5_000_000_000{polls += 1;observed=strings(walk(window));let sampled=now();if observed.contains(where:{$0.contains("COMMITTED probe-20261028-R5")}){detected=sampled;break};lastAbsent=sampled;usleep(1000)}
result["press_status"]=status.rawValue;result["action_start_ns"]=started;result["press_return_ns"]=returned;result["last_observed_absent_ns"]=lastAbsent;result["first_observed_visible_ns"]=detected;result["polls"]=polls;result["poll_sleep_us"]=1000;result["final_text"]=observed;result["scope"]="synthetic external AX evaluator mechanism, not product benchmark; polling/AX traversal latency included"
if let detected=detected{result["observed_latency_ms"]=Double(detected-started)/1_000_000}
emit(result);exit(detected != nil && status == .success && setSize == .success && actual.width==1280 && actual.height==720 ? 0:6)
