import Foundation
import Vision
import ImageIO
var frames:[[String:Double]]=[]
for path in CommandLine.arguments.dropFirst() {
    let url=URL(fileURLWithPath:path)
    let request=VNDetectFaceRectanglesRequest()
    do {
        try VNImageRequestHandler(url:url).perform([request])
        if let face=request.results?.max(by:{$0.boundingBox.width*$0.boundingBox.height < $1.boundingBox.width*$1.boundingBox.height}) {
            let box=face.boundingBox
            frames.append(["x":box.midX,"area":box.width*box.height])
        } else {frames.append([:])}
    } catch {frames.append([:])}
}
let data=try JSONSerialization.data(withJSONObject:frames)
print(String(data:data,encoding:.utf8)!)
