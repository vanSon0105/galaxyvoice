# Kế hoạch phát hành thương mại Galaxy AI Voice & Subtitle Studio

Ngày lập: 2026-08-21Trạng thái: Chờ chủ dự án chọn phương ánCăn cứ: [Rà soát phát hành thương mại](commercial-release-audit.md)

> Đây là kế hoạch kỹ thuật và tuân thủ, không thay thế tư vấn pháp lý. Mỗi pha có một
> cổng quyết định. Chưa qua cổng thì không triển khai pha phụ thuộc để tránh sửa đi sửa lại.

## Mục tiêu

Tạo một bản **Galaxy Commercial** có thể bán dưới dạng phần mềm proprietary, không
phân phối model phi thương mại, không phụ thuộc endpoint không chính thức và có đủ
cơ chế bảo vệ người dùng, dữ liệu giọng nói và quyền của bên thứ ba.

## Sơ đồ pha

```text
Pha 0: Chốt phạm vi bản thương mại
  |
  v
Pha 1: Quyết định VoiceStudio -----------+
  |                                      |
  v                                      v
Pha 2: Allowlist model              Pha 3: Thay/gỡ engine bị chặn
  |                                      |
  +------------------+-------------------+
                     v
Pha 4: Chuẩn hóa FFmpeg và codec
                     |
                     v
Pha 5: Consent, dữ liệu và chống lạm dụng
                     |
                     v
Pha 6: License, notices, SBOM và điều khoản
                     |
                     v
Pha 7: Đóng gói commercial và bảo mật cập nhật
                     |
                     v
Pha 8: Release candidate, kiểm định và mở bán thử
```

Pha 2 và Pha 3 có thể làm song song sau khi chốt Pha 1. Các pha còn lại nên đi theo
thứ tự vì đầu ra của pha trước là đầu vào kiểm định của pha sau.

## Bảng lựa chọn nhanh

Điền lựa chọn vào cột cuối trước khi bắt đầu triển khai.

| Quyết định        | A                         | B                                       | C                                         | Khuyến nghị                                                       | Lựa chọn  |
| -------------------- | ------------------------- | --------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------- | ----------- |
| VoiceStudio          | Mua commercial license    | Chỉ kết nối bản cài độc lập     | Gỡ khỏi Galaxy Commercial               | A nếu tính năng là điểm bán chính; B nếu muốn tiết kiệm | Chưa chọn |
| ProPainter           | Mua commercial license    | Gỡ/khóa khỏi bản thương mại      | Thay engine khác đã được cấp phép | B trước mắt                                                      | Chưa chọn |
| OmniVoice pretrained | Xin quyền thương mại  | Thay model thương mại                | Chỉ cho người dùng tự nhập model    | B; C vẫn cần cảnh báo và kiểm soát                           | Chưa chọn |
| IndexTTS2            | Xin quyền thương mại  | Gỡ khỏi allowlist                     | Thay model                                | B                                                                   | Chưa chọn |
| Edge TTS             | Azure Speech chính thức | TTS local có giấy phép thương mại | Giữ endpoint hiện tại                  | A hoặc B; không chọn C                                           | Chưa chọn |
| FFmpeg               | LGPL build                | Giữ GPL build và tuân thủ GPL       | Người dùng tự cài FFmpeg             | A nếu đủ codec/tính năng                                       | Chưa chọn |
| Mô hình bán       | License một lần         | Thuê bao                               | Hai phiên bản Community/Commercial      | C                                                                   | Chưa chọn |
| Dữ liệu            | Local-first               | Có cloud sync                          | Cloud-first                               | Local-first                                                         | Chưa chọn |

## Pha 0 - Chốt phạm vi và đóng băng bản hiện tại

### Nguyên nhân

Repo có code được track, runtime/model bị `.gitignore`, và nhiều file được tải trong
quá trình cài. Chỉ nhìn Git không cho biết bộ cài thực tế sẽ phân phối thứ gì. Nếu tiếp
tục thêm tính năng trong khi chưa chốt commercial scope, danh sách giấy phép sẽ tiếp
tục thay đổi.

### Công việc

1. Đặt nhãn bản hiện tại là `Development / Non-commercial` trong app và README.
2. Tạo hai profile build: `development` và `commercial`.
3. Lập distribution manifest từ bộ cài thực tế: file, nguồn, version, hash, license.
4. Chặn commercial build nếu có file/model chưa nằm trong allowlist.
5. Chụp lại dependency Python, npm, binary native và model đang cài trên máy phát hành.

### Giải pháp đề xuất

Dùng cấu hình deny-by-default: commercial build chỉ đóng gói thành phần được đánh dấu
`commercial_approved: true`. File không có metadata sẽ làm build thất bại.

### Tiêu chí hoàn thành

- Có manifest tái tạo được từ máy sạch.
- Biết chính xác kích thước và nội dung bộ cài commercial.
- Commercial build chưa thể vô tình chứa ProPainter, model NC hoặc runtime thử nghiệm.

### Cổng quyết định

- [ ] Đồng ý duy trì hai profile `development` và `commercial`.
- [ ] Chọn những tab bắt buộc phải có trong phiên bản bán đầu tiên.

Ước lượng kỹ thuật: 1-3 ngày.

## Pha 1 - Chọn chiến lược VoiceStudio

### Nguyên nhân

VoiceStudio dùng AGPL-3.0 và đang được Galaxy vendored, tự tạo runtime, tự khởi động
rồi nhúng vào tab. Đây là quyết định kiến trúc và giấy phép lớn nhất; triển khai tiếp
trước khi chốt hướng này có thể làm mất nhiều công sức.

### Phương án

**A. Mua commercial license**

- Giữ trải nghiệm tích hợp và tự khởi động hiện tại.
- Cần hợp đồng ghi rõ quyền phân phối snapshot, sửa đổi, nhúng UI, cập nhật và model.
- Commercial license của VoiceStudio không tự cấp quyền cho model bên thứ ba.

**B. Chỉ kết nối bản VoiceStudio do người dùng tự cài**

- Galaxy không phân phối, tải hộ hoặc nhúng source/runtime của VoiceStudio.
- Người dùng nhập URL local; Galaxy chỉ cung cấp connector/API adapter.
- Cần luật sư duyệt lại mức độ độc lập của hai sản phẩm.

**C. Gỡ VoiceStudio khỏi bản commercial**

- Ít rủi ro và nhẹ bộ cài nhất.
- Giữ các tính năng native của Galaxy hoặc xây lại bằng engine đã được duyệt.
- Tốn công nếu muốn đạt lại toàn bộ trải nghiệm VoiceStudio.

### Giải pháp đề xuất

Chọn A nếu VoiceStudio là điểm bán chính và chi phí license hợp lý. Nếu chưa muốn chi
tiền, chọn B cho phiên bản đầu; không tiếp tục vendored embed dưới dạng proprietary
khi chưa có văn bản cho phép.

### Tiêu chí hoàn thành

- Có văn bản cấp phép, hoặc source/runtime VoiceStudio không còn trong commercial bundle.
- UI không quảng cáo tính năng mà commercial build không có quyền cung cấp.
- Kiểm thử app khi VoiceStudio không cài hoặc không chạy.

### Cổng quyết định

- [ ] Chọn A, B hoặc C.
- [ ] Nếu A, xác nhận ngân sách và phạm vi license cần thương lượng.

Ước lượng kỹ thuật: A 1-3 ngày sau khi có license; B 3-6 ngày; C 2-4 ngày.

## Pha 2 - Lập allowlist model và engine

### Nguyên nhân

Giấy phép code của engine không đại diện cho giấy phép trọng số model. OmniVoice là
ví dụ rõ nhất: code Apache-2.0 nhưng pretrained weights là CC BY-NC. Registry động và
model ID tùy ý khiến không thể tuyên bố toàn bộ tính năng đều được phép thương mại.

### Công việc

1. Tạo schema model manifest gồm ID, revision, hash, source, code license, weight
   license, attribution, hạn chế và trạng thái phê duyệt.
2. Đánh dấu `blocked` cho OmniVoice pretrained/GGUF và IndexTTS2 hiện tại.
3. Rà từng model UVR, Demucs, Whisper, TTS và vocoder được bundle/tự tải.
4. Tách model `Galaxy approved` và `User supplied` trên giao diện.
5. Tắt tải model tùy ý trong commercial build hoặc đặt sau màn hình cảnh báo rõ ràng.

### Giải pháp đề xuất

Chỉ hiển thị model đã được phê duyệt trong luồng mặc định. Model do người dùng tự nhập
không được gắn nhãn “được Galaxy cấp phép”; vẫn cần chặn rõ model bị biết là phi thương mại.

### Tiêu chí hoàn thành

- Mọi model được commercial build tải đều có revision và hash cố định.
- Không còn model `unknown` hoặc `non-commercial` trong đường chạy mặc định.
- Attribution được tạo tự động từ manifest.

### Cổng quyết định

- [ ] Cho phép model tùy ý hay chỉ allowlist.
- [ ] Chọn model thay thế OmniVoice và IndexTTS2 để đánh giá chất lượng.

Ước lượng kỹ thuật: 3-7 ngày, chưa tính thời gian thử chất lượng model thay thế.

## Pha 3 - Thay hoặc gỡ engine bị chặn

### Nguyên nhân

ProPainter, OmniVoice weights, IndexTTS2 và Edge TTS hiện không phù hợp để trở thành
tính năng mặc định của một sản phẩm thu phí.

### Công việc theo thành phần

**ProPainter**

- Phương án nhanh: ẩn và chặn cài đặt trong commercial build; giữ Blur/Fill/Crop bằng FFmpeg.
- Phương án chất lượng: đánh giá engine inpainting có license thương mại hoặc mua quyền.

**OmniVoice và IndexTTS2**

- Gỡ preset mặc định và mọi auto-download khỏi commercial build.
- Thử model thay thế trên bộ test tiếng Việt: độ giống giọng, phát âm, tốc độ và VRAM.

**Edge TTS**

- Azure Speech: ổn định và quyền dịch vụ rõ hơn, nhưng cần tài khoản/billing.
- Local TTS: riêng tư hơn, không tính theo lượt, nhưng bộ cài lớn và phụ thuộc GPU.
- Có thể hỗ trợ cả hai và để người dùng chọn.

### Giải pháp đề xuất

Phiên bản bán đầu tiên nên khóa ProPainter, thay Edge TTS bằng Azure Speech, đồng thời
giữ một local TTS đã được duyệt làm phương án offline. Model clone chỉ bật sau khi có
model thương mại đạt kiểm thử tiếng Việt.

### Tiêu chí hoàn thành

- Commercial runtime không thể gọi hoặc cài thành phần bị chặn.
- Có migration cho config cũ đang trỏ tới engine bị loại.
- Test tự động xác nhận danh sách engine/model commercial.
- Có benchmark CPU, RTX 3060 6 GB và RTX 3060 12 GB nếu hỗ trợ local model.

### Cổng quyết định

- [ ] Chọn Azure, local TTS hoặc cả hai.
- [ ] Chọn khóa tạm hay thay thế ProPainter ngay trong v1 thương mại.
- [ ] Chấp nhận phát hành v1 chưa có voice clone nếu chưa tìm được model phù hợp.

Ước lượng kỹ thuật: 5-15 ngày, phụ thuộc engine thay thế.

## Pha 4 - Chuẩn hóa FFmpeg và codec

### Nguyên nhân

Binary hiện tại là GPLv3 build có x264/x265. Galaxy có thể gọi FFmpeg bằng subprocess,
nhưng việc phân phối binary vẫn phải tuân thủ giấy phép. Source link chung hiện chưa đủ
để truy ra exact corresponding source của binary phát hành.

### Phương án

**A. LGPL build**

- Giảm nghĩa vụ copyleft và đơn giản hóa EULA/notices.
- Có thể mất x264/x265 và một số codec/filter GPL.
- Cần test lại hardware encoder, subtitle burn-in, concat và audio pipeline.

**B. Giữ GPL build**

- Giữ đầy đủ tính năng hiện tại.
- Phải đóng gói GPL text, copyright notices, source/build scripts tương ứng và không
  hạn chế quyền GPL trong EULA.

**C. Yêu cầu người dùng tự cài FFmpeg**

- Bộ cài nhẹ và giảm trách nhiệm phân phối binary.
- Trải nghiệm cài đặt kém, khó hỗ trợ và khó tái tạo lỗi.

### Giải pháp đề xuất

Thử A trước. Nếu thiếu codec/filter bắt buộc, dùng B và tạo gói source compliance tự
động theo từng release. Dù chọn hướng nào cũng rà riêng bằng sáng chế H.264/H.265 ở
thị trường bán hàng.

### Tiêu chí hoàn thành

- Bộ test media chạy qua đúng binary sẽ phát hành.
- `About/Licenses` hiển thị version, build và giấy phép FFmpeg.
- Có source archive hoặc source offer khớp chính xác nếu giữ GPL build.

### Cổng quyết định

- [ ] Chọn A, B hoặc C sau khi chạy compatibility test.
- [ ] Chọn codec mặc định cho xuất video thương mại.

Ước lượng kỹ thuật: 2-5 ngày; tư vấn patent tách riêng.

## Pha 5 - Consent, dữ liệu và chống lạm dụng

### Nguyên nhân

Audio tham chiếu, voice embedding và profile clone có thể là dữ liệu cá nhân hoặc dữ
liệu sinh trắc học. Luồng web hiện chưa bắt buộc người dùng xác nhận quyền sử dụng
giọng nói trước khi clone/generate.

### Công việc

1. Thêm consent gate bắt buộc cho clone, design và dubbing dùng giọng tham chiếu.
2. Lưu audit record: tài khoản, thời gian, mục đích, profile, phiên bản điều khoản.
3. Thêm xem, export và xóa audio/profile/embedding/lịch sử.
4. Đặt retention mặc định và cơ chế dọn dữ liệu tự động.
5. Mã hóa dữ liệu nhạy cảm, không ghi API key/token/audio path vào log công khai.
6. Cấm giả mạo, lừa đảo và giọng người thứ ba không được phép.
7. Thêm nhãn synthetic voice/AI và quy trình report/takedown.
8. Hiển thị rõ khi nội dung được gửi tới OpenAI, DeepSeek, Azure hoặc Hugging Face.

### Giải pháp đề xuất

Giữ local-first. Cloud là opt-in theo từng tác vụ, hiển thị nhà cung cấp trước khi gửi.
Không cho chạy clone nếu consent record không hợp lệ.

### Tiêu chí hoàn thành

- Backend cưỡng chế consent, không chỉ dựa vào checkbox frontend.
- Xóa profile sẽ xóa cả file, metadata, cache và embedding liên quan.
- Có test cho consent bypass, log redaction và data deletion.
- Có bản phân loại rủi ro AI và luồng xử lý sự cố/lạm dụng.

### Cổng quyết định

- [ ] Xác nhận local-first hay cloud sync.
- [ ] Chọn thời gian retention mặc định.
- [ ] Chọn cách đánh dấu audio/video tổng hợp.

Ước lượng kỹ thuật: 5-10 ngày, cộng thời gian pháp lý soạn nội dung consent.

## Pha 6 - Hồ sơ giấy phép, SBOM và điều khoản sản phẩm

### Nguyên nhân

Repo chưa có root license/EULA, third-party notices chưa đầy đủ và VoiceStudio runtime
có hàng trăm dependency. Không có SBOM thì không thể chứng minh bộ cài chứa gì hoặc
phản ứng nhanh khi dependency có lỗ hổng.

### Công việc

1. Chọn license proprietary cho mã Galaxy và thêm copyright notice.
2. Soạn EULA, Terms of Service, Acceptable Use Policy và Privacy Policy.
3. Sinh `THIRD_PARTY_NOTICES` từ Python, npm, binary và model manifest.
4. Sinh SBOM CycloneDX hoặc SPDX cho mỗi release.
5. Ghi subprocessor: OpenAI, DeepSeek, Azure/Hugging Face nếu được dùng.
6. Nêu rõ người dùng phải có quyền với video, nhạc, phụ đề và giọng nói tải lên.
7. Tạo trang `About / Licenses / Privacy` trong app.

### Giải pháp đề xuất

Tự động hóa SBOM/notices trong build pipeline và làm build fail nếu thiếu license.
Luật sư rà nội dung pháp lý cuối, còn dữ liệu dependency do pipeline sinh.

### Tiêu chí hoàn thành

- Mỗi artifact phát hành có SBOM, notices và manifest cùng version.
- EULA không xung đột quyền LGPL/GPL của thành phần bên thứ ba.
- Người dùng xem được điều khoản trước khi kích hoạt license hoặc dùng cloud/clone.

### Cổng quyết định

- [ ] Chọn license một lần, thuê bao hay Community/Commercial.
- [ ] Chọn pháp nhân/chủ thể đứng tên phát hành và thị trường mục tiêu.

Ước lượng kỹ thuật: 3-7 ngày; thời gian luật sư nằm ngoài ước lượng.

## Pha 7 - Đóng gói commercial, cập nhật và bảo mật

### Nguyên nhân

Ngay cả khi source sạch, installer vẫn có thể vô tình đưa runtime/model ignored vào
bộ cài. Download động còn có thể thay nội dung upstream hoặc biến mất sau này.

### Công việc

1. Build từ máy/CI sạch, không lấy model từ thư mục runtime của máy developer.
2. Chỉ tải artifact theo URL versioned và kiểm tra SHA-256/signature.
3. Ký số installer và executable.
4. Tách data/model/cache khỏi code, hỗ trợ backup và uninstall sạch.
5. Thiết kế update channel, rollback và kill switch cho model có vấn đề giấy phép.
6. Chạy secret scan, dependency CVE scan và malware scan.
7. Test offline, proxy, mất mạng, hết dung lượng, thiếu CUDA và nâng cấp từ bản cũ.

### Giải pháp đề xuất

CI tạo reproducible release bundle từ manifest của Pha 0. Không cho installer tự lấy
`latest`; mọi artifact phải có version và hash cố định.

### Tiêu chí hoàn thành

- Hash của bộ cài và mọi artifact được công bố/lưu trong release record.
- Máy sạch cài và chạy được mà không dùng file ngoài manifest.
- Uninstall không xóa project/output của người dùng.
- Update lỗi có thể rollback về phiên bản trước.

### Cổng quyết định

- [ ] Chọn auto-update hay cập nhật thủ công.
- [ ] Chọn nơi lưu artifact/model mirror và thời gian duy trì phiên bản cũ.

Ước lượng kỹ thuật: 4-8 ngày.

## Pha 8 - Release candidate và quyết định mở bán

### Nguyên nhân

Compliance phải được kiểm tra trên đúng bộ cài cuối cùng. Audit source trước đó không
đủ nếu installer hoặc runtime tải thêm file trong lần chạy đầu.

### Công việc

1. Cài RC trên máy Windows sạch và ghi lại toàn bộ file/process/network request.
2. So sánh thực tế với distribution manifest và SBOM.
3. Chạy test chức năng: voice, subtitle, translation, separator, editor và export.
4. Test misuse: clone không consent, model bị block, API key trong log, path traversal.
5. Kiểm tra hiệu năng CPU, RTX 3060 6 GB/12 GB và xử lý video dài.
6. Nhờ luật sư duyệt EULA, notices, model allowlist và kiến trúc VoiceStudio đã chọn.
7. Phát hành pilot cho nhóm nhỏ, theo dõi crash, chi phí API và yêu cầu xóa dữ liệu.

### Giải pháp đề xuất

Chỉ ký quyết định `GO` khi không còn mục P0 mở. Vấn đề P1 phải có owner, deadline và
được ghi rõ là không làm thay đổi quyền thương mại của release.

### Tiêu chí hoàn thành

- Legal sign-off và technical sign-off cùng tham chiếu một release hash.
- Không phát hiện artifact không có nguồn/license.
- Không thể kích hoạt engine/model bị block bằng config cũ hoặc gọi API trực tiếp.
- Có rollback, support channel và incident response tối thiểu.

### Cổng quyết định

- [ ] `GO`: mở bán pilot.
- [ ] `CONDITIONAL GO`: chỉ khi điều kiện ghi rõ không phải vấn đề license P0.
- [ ] `NO-GO`: sửa và tạo RC mới.

Ước lượng: 3-7 ngày, không tính thời gian pilot.

## Thứ tự lựa chọn đề xuất

Để bắt đầu mà chưa phải quyết định mọi thứ cùng lúc, chủ dự án chỉ cần chọn bốn mục:

1. **VoiceStudio:** mua license, external connector hay gỡ.
2. **Bản thương mại v1:** có bắt buộc phải có voice clone và AI inpainting không.
3. **TTS:** Azure, local hay cả hai.
4. **FFmpeg:** ưu tiên LGPL hay giữ GPL và làm compliance package.

Sau bốn quyết định này có thể triển khai Pha 0-4 mà không cần chờ hoàn thiện toàn bộ
tài liệu pháp lý. Pha 5-8 tiếp tục sau khi commercial runtime đã ổn định.

## Theo dõi trạng thái

| Pha                      | Trạng thái | Quyết định còn thiếu            | Có thể bắt đầu?     |
| ------------------------ | ------------ | ------------------------------------ | ------------------------ |
| 0. Phạm vi và manifest | Chưa làm   | Danh sách tab của commercial v1    | Có                      |
| 1. VoiceStudio           | Chờ chọn   | A/B/C                                | Chưa                    |
| 2. Model allowlist       | Chờ         | Cho model tùy ý hay allowlist-only | Sau Pha 1                |
| 3. Engine thay thế      | Chờ         | TTS, clone và inpainting            | Sau Pha 1                |
| 4. FFmpeg                | Chờ chọn   | LGPL/GPL/tự cài                    | Có thể spike sớm      |
| 5. Consent và dữ liệu | Chờ         | Local/cloud và retention            | Sau Pha 2-3              |
| 6. Hồ sơ pháp lý     | Chờ         | Mô hình bán và pháp nhân       | Sau Pha 2-5              |
| 7. Đóng gói           | Chờ         | Update/mirror                        | Sau Pha 6                |
| 8. Release candidate     | Chờ         | GO/NO-GO                             | Sau tất cả pha trước |

## Ghi chú phạm vi

Kế hoạch này xử lý quyền phân phối phần mềm, model và dữ liệu. Nó không tự động cấp
quyền đối với nội dung do khách hàng đưa vào. Terms/AUP vẫn phải quy định khách hàng
chịu trách nhiệm có quyền sử dụng video, nhạc, lời thoại, phụ đề và giọng nói nguồn.
