# EDITABLE DIAGRAM SOURCES

The report uses native TikZ figures. These Mermaid equivalents support reuse in Markdown-based documentation.

## EN / 1

```mermaid
flowchart LR
 A["Agent<br/>plan / explain / edit"] --> B["MCP or REST<br/>validated request"] --> C["Decision service<br/>typed model judgment"] --> D["Structured result<br/>review flags + evidence"] --> E["Code, tests and permissions<br/>verify before acting"]
```

## EN / 2

```mermaid
flowchart LR
 A["INPUT<br/>state + questions<br/>caller + task"] --> B["VALIDATION<br/>schema and limits<br/>reject invalid input"]
 B --> C["RESULT<br/>value + probabilities<br/>review + trace"]
 B --> D["FAILURE<br/>explicit error<br/>no paid fallback"]
```

## EN / 3

```mermaid
flowchart TD
 A["1. Define success<br/>observable criteria"] --> B["2. Reproduce<br/>capture relevant evidence"] --> C["3. Choose a check<br/>exact code or short judgment"] --> D["4. Review<br/>investigate uncertainty"]
 D --> E["5. Implement<br/>small, scoped change"] --> F["6. Verify<br/>tests and actual behavior"]
 D -. Review .-> B
```

## EN / 4

```mermaid
flowchart LR
 A["Same input and criteria<br/>same model revision"] --> B["Evaluate separately<br/>correct / wrong / review"] --> C["Adopt selectively<br/>measure task-level benefit"]
```

## VI / 1

```mermaid
flowchart LR
 A["Agent chính<br/>lập kế hoạch / giải thích / sửa"] --> B["MCP hoặc REST<br/>request được kiểm tra"] --> C["Dịch vụ quyết định<br/>phán đoán theo kiểu dữ liệu"] --> D["Kết quả có cấu trúc<br/>review và bằng chứng"] --> E["Code, test và phân quyền<br/>kiểm chứng trước hành động"]
```

## VI / 2

```mermaid
flowchart LR
 A["INPUT<br/>state + questions<br/>caller + task"] --> B["KIỂM TRA<br/>schema và giới hạn<br/>từ chối input sai"]
 B --> C["KẾT QUẢ<br/>giá trị + xác suất<br/>review + trace"]
 B --> D["LỖI<br/>báo lỗi rõ ràng<br/>không fallback trả phí"]
```

## VI / 3

```mermaid
flowchart TD
 A["1. Chốt mục tiêu<br/>tiêu chí quan sát được"] --> B["2. Tái hiện<br/>giữ bằng chứng liên quan"] --> C["3. Chọn phép kiểm<br/>code hoặc phán đoán ngắn"] --> D["4. Xem lại<br/>làm rõ phần chưa chắc"]
 D --> E["5. Triển khai<br/>thay đổi nhỏ, đúng phạm vi"] --> F["6. Xác minh<br/>test và hành vi thực tế"]
 D -. Review .-> B
```

## VI / 4

```mermaid
flowchart LR
 A["Cùng input và tiêu chí<br/>cùng revision model"] --> B["Đánh giá riêng<br/>đúng / sai / cần review"] --> C["Áp dụng có chọn lọc<br/>đo lợi ích của cả tác vụ"]
```
