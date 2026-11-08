# ManageEngine APM → Splunk HEC Forwarder

Đẩy dữ liệu monitor và child-monitor từ **ManageEngine Application Manager (APM)**
sang **Splunk HTTP Event Collector (HEC)**, để telemetry của APM nằm cùng index
với phần còn lại của dữ liệu vận hành.

Chạy như Splunk scripted input, dưới cron, hoặc chạy tay. Python 3.11+, một
dependency runtime.

---

## Năng lực

| | |
|---|---|
| **Thu thập có phạm vi** | Đẩy toàn bộ monitor, hoặc giới hạn theo tên nhóm monitor. Tên nhóm không tồn tại sẽ được báo kèm danh sách nhóm APM thực sự có, thay vì âm thầm không gửi gì. |
| **Gửi theo lô** | Event được gửi dưới dạng mảng HEC, kích thước lô cấu hình được, thay vì mỗi event một request. |
| **Đọc kết quả từng event** | HEC trả `200 OK` kể cả khi từ chối event. Client đọc body và báo `code` của từng event, nên một lô bị từ chối không bao giờ bị tính là đã gửi. |
| **Retry có giới hạn** | Lỗi tạm thời (5xx, 429, lỗi kết nối) được retry với backoff. Lỗi 4xx coi là vĩnh viễn và báo ngay. |
| **Chạy lại không nhân đôi** | State file lưu fingerprint nội dung của từng monitor, nên khởi động lại hay lịch chạy chồng nhau không tạo bản trùng. State chỉ tiến khi lô gửi sạch hoàn toàn. |
| **Cô lập từng monitor** | Monitor không đọc được sẽ được ghi nhận và bỏ qua; phần còn lại của lượt chạy tiếp tục. |
| **Sạch về credential** | Không secret nào có giá trị mặc định. Cấu hình phân giải từ cờ, biến môi trường, hoặc file, theo thứ tự đó; secret được che trong mọi dòng log và mọi view trạng thái. |
| **Mặc định bật kiểm chứng TLS** | Endpoint tự ký được hỗ trợ qua CA bundle, không phải bằng cách tắt kiểm chứng. |
| **Đầu ra máy đọc được** | `--json` trên mọi lệnh; exit code phân biệt lỗi cấu hình với lỗi gửi. |

---

## Cài đặt

```bash
git clone https://github.com/TuanCui22/ManageEngine-APM-to-Splunk-HEC-Forwarder.git
cd ManageEngine-APM-to-Splunk-HEC-Forwarder
python -m pip install -e .
```

Không muốn cài: `python -m apm2splunk.cli <lệnh>`.

## Cấu hình

Ba nguồn, ưu tiên giảm dần: **cờ → biến môi trường → file config → mặc định**.

```bash
cp config.example.toml config.local.toml
# sửa config.local.toml, hoặc giữ secret trong biến môi trường:
export APM2SPLUNK_APM_API_KEY="..."
export APM2SPLUNK_HEC_TOKEN="..."
```

Bắt buộc: `apm_server`, `apm_api_key`, `hec_url`, `hec_token`, `index`. Thiếu giá
trị nào sẽ được báo ngay lúc khởi động kèm đúng tên cờ và tên biến cần đặt.

| Thiết lập | Cờ | Biến môi trường |
|---|---|---|
| APM base URL | `--apm-server` | `APM2SPLUNK_APM_SERVER` |
| APM API key | `--apm-api-key` | `APM2SPLUNK_APM_API_KEY` |
| HEC endpoint | `--hec-url` | `APM2SPLUNK_HEC_URL` |
| HEC token | `--hec-token` | `APM2SPLUNK_HEC_TOKEN` |
| Index đích | `--index` | `APM2SPLUNK_INDEX` |
| Sourcetype | `--sourcetype` | `APM2SPLUNK_SOURCETYPE` |
| Lọc theo nhóm | `--group` (lặp lại được) | `APM2SPLUNK_GROUP_NAMES` |
| Kích thước lô | `--batch-size` | `APM2SPLUNK_BATCH_SIZE` |
| State file | `--state-file` | `APM2SPLUNK_STATE_FILE` |
| CA bundle | `--ca-bundle` | `APM2SPLUNK_CA_BUNDLE` |

## Kiểm tra trước khi triển khai

```bash
apm2splunk check --config config.local.toml
```

In ra cấu hình thực tế với secret đã che, liệt kê các monitor APM báo, và gửi một
event thăm dò vô hại để xác nhận token và index. Lệnh này không đọc dữ liệu
monitor nào.

Sau đó xem trước một lượt chạy mà không gửi:

```bash
apm2splunk forward --config config.local.toml --dry-run
```

## Chạy

```bash
apm2splunk forward --config config.local.toml
```

| Exit code | Nghĩa |
|---|---|
| 0 | lượt chạy sạch |
| 1 | có monitor không đọc được, hoặc HEC từ chối event |
| 2 | cấu hình thiếu hoặc sai |
| 3 | không kết nối được APM hoặc HEC |

### Như một Splunk scripted input

`apm_to_splunk.py` và `scriptFilterGroups.py` là entry point mỏng gọi cùng một
CLI, nên scripted input có thể trỏ vào một trong hai tên đó.

```bash
# $SPLUNK_HOME/etc/apps/<app>/bin/
cp -r apm2splunk /path/to/splunk/etc/apps/<app>/bin/
cp apm_to_splunk.py /path/to/splunk/etc/apps/<app>/bin/
```

Rồi vào **Settings → Data Inputs → Scripts**, đặt interval, và cung cấp biến môi
trường qua cấu hình của input. Trỏ `--state-file` vào đường dẫn ghi được và bền,
ví dụ `$SPLUNK_HOME/var/run/apm2splunk-state.json`.

### Chỉ lấy một số nhóm

```bash
apm2splunk forward --group "Linux Group" --group "Windows Group"
```

Không truyền `--group` nghĩa là lấy tất cả.

## Trang trạng thái

```bash
apm2splunk forward --json > report.json
apm2splunk status --report report.json --out status.html
```

Một file HTML tự chứa: CSS nhúng, không request ra ngoài, không mở port. Mở trực
tiếp hoặc đặt sau bất cứ thứ gì đang serve static page. Trang chỉ hiển thị những gì
đọc được từ state file và report của lượt chạy cuối — phép đo không có được hiển
thị là không có, không bao giờ thành số 0.

## Cách gửi dữ liệu

1. `ListMonitor` → toàn bộ monitor, hoặc thành viên của các nhóm được chỉ định.
2. `GetMonitorData` cho từng monitor → một event cho monitor, một cho mỗi con.
3. Băm (fingerprint) tập event. Fingerprint không đổi thì bỏ qua monitor đó.
4. Gửi theo lô. Đọc body HEC để lấy kết quả từng event.
5. Khi gửi sạch hoàn toàn, ghi fingerprint vào state. Lỗi một phần thì để nguyên
   state, lượt sau thử lại.

## Kiểm thử

```bash
python -m pytest -q          # 28 test, không cần mạng
```

Mọi lời gọi HTTP đều được giả lập. Bộ test phủ: HEC trả 200 kèm mã từ chối, proxy
trung gian trả 200 nhưng body không phải JSON, lỗi 4xx không được retry, state file
hỏng, tên nhóm không tồn tại, và việc gộp đơn vị vào tên thuộc tính.

## Cấu trúc

```
apm2splunk/
  config.py      phân giải cờ / env / file, kiểm tra, che secret
  apm.py         client XML của APM và các parser
  hec.py         client HEC gộp lô, xử lý kết quả từng event
  forwarder.py   chu trình: liệt kê, lọc, lấy, băm, gửi
  status.py      trang HTML trạng thái tự chứa
  cli.py         forward / check / status
tests/
  test_apm2splunk.py
apm_to_splunk.py        entry point
scriptFilterGroups.py   entry point
```

## Giấy phép

Artefact nghiên cứu riêng. Không phải open source, không phân phối lại. Xem
[`LICENSE`](LICENSE) và [`NOTICE`](NOTICE).
