# ManageEngine APM → Splunk HEC Forwarder

Lấy dữ liệu monitor từ **ManageEngine Application Manager (APM)** và đẩy sang
**Splunk HTTP Event Collector (HEC)**, để metric của APM nằm cùng chỗ với mọi thứ
khác trên indexer, thay vì nằm trong một dashboard không ai mở.

Chạy được như Splunk scripted input, như cron job, hoặc chạy tay. Python 3.11+,
một dependency runtime.

---

## Bản 2.0 khác gì bản 1.x

Script 1.x chạy được, nhưng có bốn vấn đề chỉ lộ ra khi lên production:

| Bản 1.x | Bản 2.0 |
|---|---|
| API key APM và HEC token hard-code trong file | cờ dòng lệnh, biến môi trường, hoặc file config — không có secret trong repo |
| `verify=False` ở mọi request | mặc định bật kiểm chứng TLS; dùng `--ca-bundle` cho chứng chỉ tự ký |
| mỗi event một request HTTP | gộp lô, 100 event mỗi request |
| chỉ kiểm `status_code == 200` | đọc body của HEC — HEC trả **200 trong khi vẫn drop event** |
| không có timeout | có timeout mỗi request, retry có giới hạn |
| gửi lại toàn bộ mỗi chu kỳ | có state file; chạy lại không nhân đôi một cửa sổ |
| một monitor lỗi là chết cả lượt chạy | cô lập từng monitor, báo lỗi theo từng monitor |
| hai script, hai cách hành xử | một CLI: `forward`, `check`, `status` |

Dòng cuối là dòng quan trọng nhất. HEC trả `200 OK` kèm
`{"code": 5, "text": "No index"}` khi nó từ chối event của bạn. Script 1.x vẫn in
"Sent to Splunk" cho từng event một.

---

## Cài đặt

```bash
git clone https://github.com/TuanCui22/ManageEngine-APM-to-Splunk-HEC-Forwarder.git
cd ManageEngine-APM-to-Splunk-HEC-Forwarder
python -m pip install -e .
```

Không muốn cài: `python -m apm2splunk.cli <lệnh>`.

## Cấu hình

Ba nguồn, ưu tiên giảm dần: **cờ dòng lệnh → biến môi trường → file config → mặc định**.

```bash
cp config.example.toml config.local.toml
# sửa config.local.toml, hoặc giữ secret ra ngoài hoàn toàn:
export APM2SPLUNK_APM_API_KEY="..."
export APM2SPLUNK_HEC_TOKEN="..."
```

Tối thiểu phải đặt: `apm_server`, `apm_api_key`, `hec_url`, `hec_token`, `index`.
Thiếu một cái là lỗi ngay lúc khởi động, không phải im lặng hỏng lúc 3 giờ sáng.

## Kiểm tra trước khi triển khai

```bash
apm2splunk check --config config.local.toml
```

Lệnh này in ra cấu hình thực tế với secret đã che, liệt kê các monitor mà APM báo,
và gửi **một** event thăm dò vô hại để chứng minh token và index đúng. Nó không
đụng vào dữ liệu monitor nào.

Sau đó xem trước những gì sẽ gửi, mà không gửi thật:

```bash
apm2splunk forward --config config.local.toml --dry-run
```

## Chạy

```bash
apm2splunk forward --config config.local.toml
```

Exit code, vì scripted input của Splunk chỉ đọc được tín hiệu đó:

| mã | nghĩa |
|---|---|
| 0 | lượt chạy sạch |
| 1 | có monitor không đọc được, hoặc HEC từ chối event |
| 2 | cấu hình thiếu hoặc sai |
| 3 | không kết nối được APM hoặc HEC |

### Như một Splunk scripted input

Entry point cũ vẫn chạy — `apm_to_splunk.py` và `scriptFilterGroups.py` giờ chỉ là
lớp mỏng gọi CLI mới, nên input đang có không phải sửa gì.

```bash
# $SPLUNK_HOME/etc/apps/<app>/bin/
cp -r apm2splunk /path/to/splunk/etc/apps/<app>/bin/
cp apm_to_splunk.py /path/to/splunk/etc/apps/<app>/bin/
```

Rồi vào **Settings → Data Inputs → Scripts**, interval `60`, và đặt biến môi
trường trong cấu hình của input (hoặc trong `bin/.env` nếu bạn có wrapper đọc file
đó). Nhớ trỏ state file vào chỗ ghi được —
`$SPLUNK_HOME/var/run/apm2splunk-state.json` là lựa chọn hợp lý.

### Chỉ lấy một số group

```bash
apm2splunk forward --group "Linux Group" --group "Windows Group"
```

Không truyền `--group` nghĩa là lấy tất cả. Một tên group không tồn tại sẽ là lỗi
kèm danh sách tên group APM thực sự báo — thay vì âm thầm không gửi gì.

## Trang trạng thái

```bash
apm2splunk forward --json > report.json
apm2splunk status --report report.json --out status.html
```

Một file HTML tự chứa: CSS nhúng, không có script nào gọi ra ngoài, không request
mạng. Mở trực tiếp hoặc đặt sau bất cứ thứ gì đang serve static page. Trang chỉ báo
những gì nó đọc được từ state file và report của lượt chạy cuối — giá trị không đọc
được hiện ra thành khoảng trống có tên, không bao giờ thành số 0.

## Nó quyết định gửi gì như thế nào

1. `ListMonitor` → toàn bộ monitor, hoặc chỉ thành viên của các group bạn chỉ định.
2. `GetMonitorData` cho từng monitor → một event cho monitor, một event cho mỗi con.
3. Băm (fingerprint) tập event. Nếu trùng với lần gửi trước của monitor đó thì bỏ
   qua. Đây là thứ làm cho việc chạy lại không nhân đôi dữ liệu.
4. Gửi theo lô `batch_size`. Đọc body HEC để biết kết quả từng event.
5. Chỉ khi gửi sạch hoàn toàn mới ghi fingerprint vào state file. Lỗi một phần thì
   để nguyên state, lượt sau sẽ thử lại.

## Kiểm thử

```bash
python -m pytest -q          # 28 test, không cần mạng
```

Mọi lời gọi HTTP trong bộ test đều được giả lập. Test phủ đúng những chỗ dễ hỏng:
HEC trả 200 kèm mã từ chối, proxy trả 200 nhưng body không phải JSON, lỗi 4xx
không được retry, state file hỏng, tên group không tồn tại, và việc gộp đơn vị vào
tên thuộc tính.

## Cấu trúc

```
apm2splunk/
  config.py      phân giải cờ / env / file, kiểm tra, che secret
  apm.py         client XML của APM và các parser
  hec.py         client HEC có gộp lô, xử lý kết quả từng event
  forwarder.py   chu trình: liệt kê, lọc, lấy, băm, gửi
  status.py      trang HTML trạng thái tự chứa
  cli.py         forward / check / status
tests/
  test_apm2splunk.py
apm_to_splunk.py        lớp tương thích 1.x
scriptFilterGroups.py   lớp tương thích 1.x
```

## Giấy phép

Artefact nghiên cứu riêng. Không phải open source, không phân phối lại. Xem
[`LICENSE`](LICENSE) và [`NOTICE`](NOTICE).
