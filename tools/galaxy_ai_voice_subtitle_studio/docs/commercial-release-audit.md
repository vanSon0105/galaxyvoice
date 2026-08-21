# Rà soát phát hành thương mại Galaxy AI Voice & Subtitle Studio

Ngày rà soát: 2026-08-21

Kế hoạch xử lý theo pha: [Kế hoạch phát hành thương mại](commercial-release-plan.md)

> Tài liệu này là rà soát kỹ thuật và giấy phép nguồn mở, không phải ý kiến tư vấn
> pháp lý. Trước khi thu tiền hoặc phát hành bộ cài, nên nhờ luật sư sở hữu trí tuệ
> và bảo vệ dữ liệu kiểm tra bản phát hành cuối cùng.

## Kết luận điều hành

**Chưa nên phát hành thương mại bản hiện tại nguyên trạng.** Dự án có một số thành
phần được phép dùng thương mại, nhưng đang tích hợp hoặc hỗ trợ tải các thành phần
không thương mại, có copyleft mạnh, hoặc phụ thuộc dịch vụ không được cấp quyền rõ
ràng cho sản phẩm thương mại.

Các điểm chặn phát hành chính:

1. ProPainter chỉ cấp phép cho mục đích phi thương mại.
2. Model mặc định `k2-fsa/OmniVoice` dùng giấy phép CC BY-NC 4.0 cho trọng số.
3. IndexTTS2 được VoiceStudio hỗ trợ nhưng giấy phép model là nghiên cứu/phi thương mại.
4. VoiceStudio là AGPL-3.0; cách Galaxy đóng gói, tự khởi động và nhúng giao diện làm
   tăng đáng kể nguy cơ Galaxy bị xem là một sản phẩm kết hợp. Bản đóng mã nguồn cần
   giấy phép thương mại từ tác giả hoặc ý kiến pháp lý xác nhận kiến trúc phân tách.
5. `edge-tts` gọi endpoint giọng nói tiêu dùng không chính thức của Microsoft; giấy
   phép mã nguồn không đồng nghĩa có quyền thương mại đối với dịch vụ.
6. FFmpeg đang đóng gói là bản GPLv3 có x264/x265, nhưng bộ phát hành chưa có gói
   tuân thủ GPL đầy đủ.
7. Chưa có EULA, chính sách riêng tư, quy trình đồng ý nhái giọng, danh mục model được
   duyệt, SBOM và bộ thông báo giấy phép đầy đủ.

## Phạm vi rà soát

- Mã nguồn Galaxy và các dependency Python/JavaScript khai báo trong dự án.
- VoiceStudio được vendored tại `vendor/voicestudio` và cách Galaxy khởi chạy/nhúng nó.
- OmniVoice, các engine/model do VoiceStudio hỗ trợ, ProPainter và audio separator/UVR.
- FFmpeg được đóng gói trong `bin` hoặc tải bởi script cài đặt.
- OpenAI, DeepSeek, Hugging Face và Microsoft Edge TTS.
- Các rủi ro về dữ liệu giọng nói, nhái giọng và nội dung AI tại Việt Nam.

Không thể cấp phép chung cho mọi model Hugging Face mà người dùng nhập tùy ý. Mỗi
model phải được xét theo giấy phép tại đúng revision đã tải.

## Thành phần chặn phát hành

| Thành phần | Bằng chứng | Rủi ro thương mại | Hành động bắt buộc |
| --- | --- | --- | --- |
| ProPainter / Fast AI xóa phụ đề | Script cài đặt yêu cầu chấp nhận giấy phép phi thương mại; upstream ghi rõ code và model chỉ dùng phi thương mại | Rất cao | Gỡ hoặc khóa khỏi bản thương mại, hoặc xin giấy phép thương mại bằng văn bản |
| `k2-fsa/OmniVoice` | Code Apache-2.0 nhưng model card ghi trọng số CC BY-NC do ràng buộc dữ liệu huấn luyện | Rất cao | Không đóng gói, tải mặc định hoặc dùng để cung cấp tính năng có thu tiền; thay bằng model được phép thương mại hoặc xin phép |
| OmniVoice GGUF | Là trọng số dẫn xuất từ OmniVoice | Rất cao | Áp dụng cùng hạn chế phi thương mại như model gốc |
| IndexTTS2 | Tài liệu engine trong VoiceStudio ghi giấy phép nghiên cứu/phi thương mại, muốn thương mại phải liên hệ tác giả | Rất cao | Loại khỏi allowlist thương mại hoặc mua quyền sử dụng |
| VoiceStudio 0.4.2 | Snapshot vendored dùng AGPL-3.0-only; tác giả yêu cầu giấy phép thương mại khi nhúng vào sản phẩm đóng | Cao | Khuyến nghị mua giấy phép thương mại. Phương án khác là bỏ vendored/embed và chỉ kết nối tùy chọn tới bản cài độc lập, sau khi được luật sư duyệt |
| `edge-tts` | Thư viện mã nguồn LGPL nhưng dùng endpoint tiêu dùng không chính thức; maintainer không khuyến nghị cho sản phẩm thương mại | Cao | Thay bằng Azure AI Speech chính thức hoặc TTS local/model có giấy phép thương mại |
| FFmpeg GPL build | Binary hiện tại có `--enable-gpl --enable-version3`, x264 và x265 | Cao | Chuyển sang LGPL build nếu đủ tính năng, hoặc cung cấp đầy đủ license, notices, corresponding source/build scripts và quyền GPL |

### ProPainter

`install_propainter.ps1` và mã dịch vụ đã nhận biết giấy phép phi thương mại. Tuy nhiên,
checkbox chấp nhận giấy phép không biến hoạt động thương mại thành hợp lệ. Nếu Galaxy
được bán, thuê bao, quảng cáo hoặc dùng trong dịch vụ kiếm tiền, tính năng này cần bị
loại khỏi bản thương mại cho tới khi có giấy phép riêng.

### OmniVoice

Cần phân biệt hai tài sản:

- **Mã nguồn/package OmniVoice:** Apache-2.0.
- **Trọng số pretrained `k2-fsa/OmniVoice`:** CC BY-NC 4.0.

Galaxy hiện dùng model này làm mặc định trong `app/omnivoice/models.py`,
`app/omnivoice/worker.py` và giao diện Studio. Vì sản phẩm không hoạt động như mong
đợi nếu chỉ có code mà không có trọng số, giấy phép model mới là điều quyết định cho
tính năng nhái giọng thực tế.

Token Hugging Face chỉ xác thực quyền tải. Token không cấp thêm quyền thương mại và
không thay đổi giấy phép của repository/model.

### VoiceStudio và AGPL

Galaxy hiện không chỉ cung cấp một URL tới ứng dụng bên ngoài. Nó giữ snapshot
VoiceStudio trong repo, tạo runtime, khởi chạy backend ở loopback và nhúng frontend
vào tab của Galaxy. Dù tiến trình riêng và giao tiếp qua HTTP là yếu tố có lợi cho lập
luận “hai chương trình độc lập”, đây không phải vùng an toàn chắc chắn vì sản phẩm được
đóng gói và trình bày như một tính năng thống nhất.

Không nên khẳng định tự động rằng toàn bộ Galaxy bắt buộc phải AGPL nếu chưa có ý kiến
luật sư. Tuy vậy, với mục tiêu bán bản proprietary, phương án ít rủi ro nhất là:

1. Mua giấy phép thương mại VoiceStudio từ tác giả; hoặc
2. Không phân phối, tự cài, tự chạy hoặc nhúng VoiceStudio. Chỉ cho phép người dùng tự
   cài một dịch vụ độc lập rồi nhập URL kết nối.

Mở mã nguồn Galaxy theo AGPL có thể xử lý một phần nghĩa vụ copyleft, nhưng **không**
gỡ được hạn chế phi thương mại của OmniVoice, IndexTTS2 hay ProPainter.

### FFmpeg và codec

Galaxy gọi FFmpeg bằng subprocess nên bản thân Galaxy không nhất thiết phải chuyển
sang GPL. Nghĩa vụ chính nằm ở việc phân phối binary GPL:

- Kèm đúng văn bản GPL và copyright notices.
- Chỉ rõ build/version đã phân phối.
- Cung cấp exact corresponding source và script/cấu hình build, hoặc một written
  offer hợp lệ theo GPL.
- Không đặt điều khoản EULA hạn chế các quyền mà GPL cấp cho binary FFmpeg.

File `bin/FFMPEG_SOURCE.txt` hiện chỉ trỏ tới trang chung, chưa đủ để chứng minh đã
cung cấp đúng source tương ứng. H.264/H.265 còn có rủi ro bằng sáng chế tách biệt với
giấy phép phần mềm; cần kiểm tra theo quốc gia bán hàng và phương thức phân phối.

## Thành phần có thể dùng có điều kiện

| Thành phần | Đánh giá | Điều kiện |
| --- | --- | --- |
| Mã Galaxy do chủ dự án viết | Có thể thương mại hóa | Xác nhận toàn bộ contributor/IP; thêm EULA hoặc LICENSE proprietary rõ ràng |
| FastAPI, React, Vite, TanStack Query và phần lớn dependency chính | Chủ yếu MIT/BSD/ISC | Giữ copyright notices, license text và kiểm tra cả dependency bắc cầu |
| `faster-whisper` | Mã nguồn permissive | Giữ notices; kiểm tra riêng giấy phép từng Whisper/model tải về |
| `audio-separator` | Wrapper MIT | Giữ attribution; xét riêng từng UVR/Demucs model |
| UVR code | MIT | Ghi công; không suy ra mọi model UVR đều MIT |
| Windows SAPI | Gọi API hệ thống có rủi ro thấp hơn | Không đóng gói hoặc tái phân phối dữ liệu giọng Microsoft nếu chưa có quyền |
| OpenAI API | Cho phép tích hợp API vào ứng dụng | Dùng API billing, tuân thủ Services Agreement, privacy và quyền đối với input |
| DeepSeek API | Cho phép ứng dụng downstream theo điều khoản | Thông báo nhà cung cấp, xử lý dữ liệu, consent và trách nhiệm end-user |

## Model và engine cần allowlist

VoiceStudio có registry động và cho phép tải nhiều model. Không nên để một model xuất
hiện trong bản thương mại chỉ vì engine chạy được. Mỗi mục trong allowlist cần có:

- Model ID và revision/commit SHA cố định.
- URL nguồn và hash của file tải.
- Giấy phép code, giấy phép model và giấy phép dữ liệu nếu được công bố.
- Quyền thương mại: `approved`, `blocked` hoặc `legal-review`.
- Attribution bắt buộc và hạn chế sử dụng.
- Phiên bản tokenizer/vocoder/phụ trợ, vì chúng có thể mang giấy phép khác.

Các engine như Supertonic, PocketTTS, MOSS-TTS, CosyVoice, Qwen TTS, Dia,
Chatterbox, MeloTTS và OuteTTS phải được kiểm tra tại đúng model repository. Giấy phép
của wrapper MLX hoặc engine không tự động bao phủ trọng số upstream.

## Audio separator và UVR

Runtime local hiện có nhiều model như Kim Vocal, UVR-MDX-NET, Apollo và Demucs.
Upstream UVR và `audio-separator` có mã nguồn permissive, nhưng provenance/giấy phép
của toàn bộ file model đang cài chưa được ghi thành manifest. Vì vậy:

1. Không đóng gói nguyên thư mục runtime/model vào installer thương mại ở trạng thái hiện tại.
2. Lập manifest theo từng model và chỉ đóng gói model đã được duyệt.
3. Kèm attribution cho UVR, tác giả model và `audio-separator`.
4. Tách rõ model do Galaxy cung cấp với model do người dùng tự thêm.

## Dữ liệu cá nhân, nhái giọng và nội dung AI

Giọng nói, bản ghi âm và profile clone có thể là dữ liệu cá nhân hoặc dữ liệu sinh
trắc học. Bản thương mại cần ít nhất:

- Checkbox xác nhận người dùng là chủ giọng nói hoặc có quyền/đồng ý hợp lệ.
- Ghi nhận thời điểm, mục đích, tài khoản và phiên bản điều khoản đã chấp nhận.
- Cơ chế xóa profile, audio mẫu, embedding và lịch sử liên quan.
- Chính sách lưu trữ, mã hóa, kiểm soát truy cập và thời hạn xóa.
- Cấm giả mạo, lừa đảo, nhái người nổi tiếng/người thứ ba không được phép.
- Cơ chế báo cáo lạm dụng và gỡ nội dung.
- Nhãn hoặc metadata nhận biết nội dung tổng hợp khi pháp luật/nền tảng yêu cầu.

Luật Trí tuệ nhân tạo Việt Nam có hiệu lực từ 2026-03-01 và Nghị định 142/2026 yêu
cầu phân loại rủi ro trước khi đưa hệ thống vào sử dụng; bên tích hợp phải đánh giá
lại khi việc tích hợp làm tăng rủi ro. Luật Bảo vệ dữ liệu cá nhân có hiệu lực từ
2026-01-01 làm consent, mục đích xử lý và an toàn dữ liệu trở thành phần bắt buộc của
thiết kế, không chỉ là nội dung trong điều khoản sử dụng.

Galaxy hiện chưa có consent gate bắt buộc ở luồng clone voice web. Đây là một điểm
chặn phát hành, kể cả sau khi đã thay model.

## Tài liệu pháp lý và vận hành còn thiếu

- EULA/điều khoản cấp phép Galaxy và thông báo bản quyền của chủ dự án.
- Terms of Service và Acceptable Use Policy.
- Privacy Policy, danh sách subprocessor và thông báo gửi dữ liệu lên OpenAI/DeepSeek.
- Quy trình DMCA/takedown hoặc quy trình xử lý khiếu nại phù hợp thị trường bán hàng.
- `THIRD_PARTY_NOTICES` đầy đủ; file hiện tại mới chủ yếu nói về VoiceStudio.
- SBOM CycloneDX/SPDX cho Python, npm, binary native, model và runtime tải động.
- Quy trình scan CVE, malware, secret và ký số installer theo từng release.
- Manifest chính xác những file ignored nhưng vẫn được đưa vào bộ cài.

Repo chưa có `LICENSE` ở root. Repo công khai không đồng nghĩa người khác được quyền
sử dụng lại, nhưng cũng không nói rõ quyền của khách hàng. Nếu chọn proprietary, cần
thêm license/EULA proprietary và tách riêng các thành phần third-party theo giấy phép
của chúng.

## Lộ trình phát hành khuyến nghị

### Phương án A: bản proprietary thương mại

Đây là hướng phù hợp nhất nếu muốn bán tool mà không công khai toàn bộ mã nguồn.

**P0 - phải hoàn thành trước khi phát hành:**

1. Gỡ/khóa ProPainter và IndexTTS2 khỏi commercial build, hoặc có giấy phép thương mại.
2. Thay OmniVoice pretrained bằng model được phép thương mại; không tải model NC mặc định.
3. Mua commercial license VoiceStudio hoặc bỏ hoàn toàn vendored/auto-install/embed.
4. Thay `edge-tts` bằng Azure Speech chính thức hoặc TTS local đã được duyệt.
5. Chọn FFmpeg LGPL build hoặc hoàn thiện gói tuân thủ GPL.
6. Bổ sung consent gate và các kiểm soát lạm dụng cho clone/design/dubbing.
7. Tạo model allowlist, SBOM, notices, EULA, Terms và Privacy Policy.

**P1 - trước khi mở bán rộng rãi:**

1. Kiểm tra bằng sáng chế codec theo các thị trường mục tiêu.
2. Kiểm tra toàn bộ model UVR và VoiceStudio theo revision cụ thể.
3. Khóa dependency và download URL bằng version/hash; có mirror hợp pháp.
4. Tạo chức năng export/delete dữ liệu người dùng và thời hạn retention mặc định.
5. Thực hiện security review, secret scan, CVE scan và ký số bộ cài.
6. Gắn nhãn AI/synthetic media và lưu audit event cho thao tác nhạy cảm.

### Phương án B: phát hành nguồn mở AGPL

Có thể giảm xung đột với VoiceStudio nếu Galaxy và cách cung cấp qua mạng tuân thủ
AGPL đầy đủ. Tuy nhiên phương án này vẫn không cho phép dùng thương mại các trọng số
CC BY-NC hay ProPainter/IndexTTS2. Các thành phần đó vẫn phải gỡ hoặc xin phép.

## Nguồn chính

- [VoiceStudio README và điều khoản commercial embedding](https://github.com/debpalash/VoiceStudio/blob/main/README.md)
- [VoiceStudio AGPL-3.0 license](https://github.com/debpalash/VoiceStudio/blob/main/LICENSE)
- [GNU GPL FAQ về aggregate và giao tiếp giữa chương trình](https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation)
- [OmniVoice model card: code Apache-2.0, weights CC BY-NC](https://huggingface.co/k2-fsa/OmniVoice)
- [Creative Commons BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
- [Hugging Face Terms of Service](https://huggingface.co/terms-of-service)
- [ProPainter repository và NTU S-Lab License 1.0](https://github.com/sczhou/ProPainter)
- [Ultimate Vocal Remover repository](https://github.com/Anjok07/ultimatevocalremovergui)
- [`audio-separator` repository](https://github.com/nomadkaraoke/python-audio-separator)
- [FFmpeg legal information](https://ffmpeg.org/legal.html)
- [BtbN FFmpeg build variants](https://github.com/BtbN/FFmpeg-Builds)
- [H.264 patent pool information](https://www.via-la.com/licensing-programs/avc-h-264/)
- [HEVC patent pool information](https://accessadvance.com/)
- [`edge-tts` commercial-use discussion](https://github.com/rany2/edge-tts/discussions/261)
- [Azure Speech text-to-speech transparency note](https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/speech-service/text-to-speech/transparency-note)
- [OpenAI Services Agreement](https://openai.com/policies/services-agreement/)
- [DeepSeek Open Platform Terms](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html)
- [DeepSeek Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)
- [Luật Trí tuệ nhân tạo số 134/2025/QH15](https://vanban.chinhphu.vn/?classid=1&docid=216334&pageid=27160&typegroupid=3)
- [Nghị định 142/2026/NĐ-CP](https://vanban.chinhphu.vn/?docid=218029&orggroupid=2&pageid=27160)
- [Quy định về dữ liệu cá nhân từ ghi âm, ghi hình](https://xaydungchinhsach.chinhphu.vn/quy-dinh-bao-ve-du-lieu-ca-nhan-thu-duoc-tu-hoat-dong-ghi-am-ghi-hinh-tai-noi-cong-119250730154729554.htm)
- [Quy định về dữ liệu sinh trắc học](https://xaydungchinhsach.chinhphu.vn/quy-dinh-bao-ve-du-lieu-ca-nhan-doi-voi-du-lieu-vi-tri-ca-nhan-du-lieu-sinh-trac-hoc-119250730155653784.htm)
- [Quyền tác giả đối với tác phẩm có AI hỗ trợ](https://baochinhphu.vn/dieu-kien-de-tac-pham-do-ai-ho-tro-tao-ra-duoc-phap-luat-bao-ho-quyen-tac-gia-102260415163902936.htm)

## Quyết định đề xuất

Đóng nhãn bản hiện tại là **development/non-commercial**. Bắt đầu một commercial
build profile riêng, mặc định chỉ bật dependency và model nằm trong allowlist. Chỉ
mở bán khi toàn bộ mục P0 có bằng chứng hoàn thành và bộ cài cuối đã được kiểm tra lại
theo đúng manifest phát hành.
