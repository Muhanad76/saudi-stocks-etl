# دليل بناء داشبورد Power BI

## 1. الربط بقاعدة MySQL

1. ثبّت **MySQL Connector/NET** من موقع MySQL الرسمي (مطلوب، بدونه ما يظهر خيار MySQL أو يطلع خطأ).
2. في Power BI: **Get Data → MySQL database**
   - Server: `localhost`
   - Database: `saudi_stocks`
3. اختر الجداول: `companies` و `daily_prices` و `daily_metrics`.
4. وضع الاتصال: **Import** (موصل MySQL في Power BI Desktop يدعم Import فقط).
   بعد كل تشغيل لـ `pipeline.py` اضغط **Refresh** وتتحدث البيانات.

## 2. النموذج (Model)

أنشئ جدول تواريخ: **Modeling → New table**

```DAX
Date =
ADDCOLUMNS (
    CALENDAR ( MIN ( daily_prices[date] ), MAX ( daily_prices[date] ) ),
    "Year", YEAR ( [Date] ),
    "Month No", MONTH ( [Date] ),
    "Month", FORMAT ( [Date], "MMM" ),
    "Year-Month", FORMAT ( [Date], "YYYY-MM" )
)
```

علّمه كجدول تواريخ: كليك يمين → **Mark as date table** → عمود `Date`.
رتّب عمود `Month` حسب `Month No` (**Sort by column**).

العلاقات (كلها واحد إلى متعدد، اتجاه فلتر واحد):

| من | إلى |
|----|-----|
| `companies[ticker]` | `daily_prices[ticker]` |
| `companies[ticker]` | `daily_metrics[ticker]` |
| `Date[Date]` | `daily_prices[date]` |
| `Date[Date]` | `daily_metrics[date]` |

لا تربط `daily_prices` مع `daily_metrics` مباشرة. الاثنين يتفلترون عن طريق `companies` و `Date`.

## 3. مقاييس DAX

أنشئ جدول فاضي اسمه `_Measures` وحط فيه المقاييس عشان تكون مرتبة.

### أسعار وحجم

```DAX
Latest Close =
VAR LastDate = MAX ( daily_prices[date] )
RETURN CALCULATE ( AVERAGE ( daily_prices[close] ), daily_prices[date] = LastDate )
```
آخر سعر إغلاق ضمن الفترة المختارة. للبطاقات (KPI) مع فلتر سهم واحد.

```DAX
Total Volume = SUM ( daily_prices[volume] )

Avg Daily Volume = AVERAGE ( daily_prices[volume] )
```
مجموع ومتوسط حجم التداول اليومي، لسؤال المواسم (رسم أعمدة حسب `Date[Month]`).
`AVERAGE` يتجاهل الأيام اللي الحجم فيها NULL (بيانات Yahoo الخربانة من مارس إلى يونيو 2023)، فالمتوسط يطلع صحيح. لا تقسم المجموع على عدد الأيام، لأن الأيام الفاضية بتدخل في القسمة وتنزّل المتوسط.

### العائد

```DAX
Period Return % =
VAR FirstDate = MIN ( daily_prices[date] )
VAR LastDate  = MAX ( daily_prices[date] )
VAR FirstClose = CALCULATE ( AVERAGE ( daily_prices[close] ), daily_prices[date] = FirstDate )
VAR LastClose  = CALCULATE ( AVERAGE ( daily_prices[close] ), daily_prices[date] = LastDate )
RETURN DIVIDE ( LastClose, FirstClose ) - 1
```
عائد السهم من أول يوم لآخر يوم في الفترة المختارة بالـ slicer. يتغير تلقائياً مع فلتر التاريخ، فهو أدق من `cumulative_return` المخزن (اللي يبدأ دايماً من أول يوم في القاعدة).

```DAX
Avg Stock Return % =
AVERAGEX ( VALUES ( companies[ticker] ), [Period Return %] )
```
متوسط عوائد الأسهم. استخدمه لمقارنة القطاعات: حط `companies[sector]` في المحور، فيحسب عائد كل سهم لحاله وبعدين يأخذ المتوسط.

```DAX
Return Since Start % =
VAR _FirstDate =
    CALCULATE ( MIN ( daily_prices[date] ), ALLSELECTED ( 'Date' ) )
VAR _FirstClose =
    CALCULATE ( AVERAGE ( daily_prices[close] ), ALLSELECTED ( 'Date' ), daily_prices[date] = _FirstDate )
VAR _Close = AVERAGE ( daily_prices[close] )
RETURN IF ( NOT ISBLANK ( _Close ), DIVIDE ( _Close, _FirstClose ) - 1 )
```
للرسم الخطي اللي يقارن الأسهم: كل الخطوط تبدأ من 0% عند بداية الفترة المختارة. بدونه سهم سعره 100 وسهم سعره 20 ما تقدر تقارنهم.
شرط `IF ( NOT ISBLANK ( _Close ) ...)` مهم: في الأيام اللي ما فيها تداول للسهم يكون السعر فاضي، وبدون الشرط يطلع الناتج -100% وينزل الخط للقاع.

### المخاطرة

```DAX
Annual Volatility % =
STDEV.S ( daily_metrics[daily_return] ) * SQRT ( 250 )
```
التذبذب السنوي = الانحراف المعياري للعائد اليومي × جذر 250 (عدد أيام التداول تقريباً في السنة). كل ما زاد، زادت المخاطرة.

```DAX
Max Drawdown % =
VAR Prices =
    ADDCOLUMNS (
        VALUES ( daily_prices[date] ),
        "@close", CALCULATE ( AVERAGE ( daily_prices[close] ) ),
        "@peak",
            VAR d = daily_prices[date]
            RETURN CALCULATE ( MAX ( daily_prices[close] ), daily_prices[date] <= d, ALLSELECTED ( daily_prices[date] ) )
    )
RETURN MINX ( Prices, DIVIDE ( [@close], [@peak] ) - 1 )
```
أكبر نزول من قمة سابقة. يستخدم مع سهم واحد (صفحة تفاصيل السهم).

```DAX
Return / Risk = DIVIDE ( [Period Return %], [Annual Volatility %] )
```
كم عائد تأخذ مقابل كل وحدة مخاطرة. أعلى = أفضل.

### أفضل وأسوأ سهم

```DAX
Best Performer =
VAR Top1 = TOPN ( 1, VALUES ( companies[name_en] ), [Period Return %], DESC )
RETURN CONCATENATEX ( Top1, companies[name_en], ", " )

Worst Performer =
VAR Bottom1 = TOPN ( 1, VALUES ( companies[name_en] ), [Period Return %], ASC )
RETURN CONCATENATEX ( Bottom1, companies[name_en], ", " )
```
للبطاقات في صفحة النظرة العامة.

### المتوسطات المتحركة

```DAX
MA 20 = AVERAGE ( daily_metrics[ma_20] )
MA 50 = AVERAGE ( daily_metrics[ma_50] )
Close Price = AVERAGE ( daily_prices[close] )
```
ثلاث خطوط على نفس الرسم في صفحة تفاصيل السهم.

## 4. الصفحات

### الصفحة 1: Overview
- **Slicer** للتاريخ (`Date[Date]`، نوع Between).
- **بطاقات KPI**: `Best Performer`، `Worst Performer`، `Avg Stock Return %`، `Total Volume`.
- **Bar chart**: `companies[name_en]` × `Period Return %`، مرتب تنازلياً، مع تلوين شرطي (أخضر موجب، أحمر سالب).
- **Line chart**: `Date[Date]` × `Return Since Start %`، والـ Legend = `companies[name_en]`.

### الصفحة 2: Stock Detail
- **Slicer** لسهم واحد (`companies[name_en]`، Single select).
- **بطاقات**: `Latest Close`، `Period Return %`، `Annual Volatility %`، `Max Drawdown %`.
- **Line chart**: `Close Price` و `MA 20` و `MA 50` على محور التاريخ.
- **Column chart**: `Date[Year-Month]` × `Total Volume`.

### الصفحة 3: Sector Comparison
- **Clustered bar**: `companies[sector]` × `Avg Stock Return %`.
- **Scatter chart**: X = `Annual Volatility %`، Y = `Period Return %`، Details = `companies[name_en]`، Legend = `companies[sector]`. هذا يوضح العلاقة بين العائد والمخاطرة.
- **Column chart** للمواسم: `Date[Month]` × `Avg Daily Volume`.

### (اختياري) الصفحة 4: Correlation
الارتباط ثقيل بـ DAX. الأسهل:
**Get Data → MySQL database → Advanced options → SQL statement**، والصق استعلام **Q7** من `sql/analysis.sql`.
بعدها **Matrix**: Rows = `ticker_1`، Columns = `ticker_2`، Values = `correlation`، مع **Conditional formatting → Background color** (تدرج لوني).

## 5. لمسات أخيرة
- ثيم موحد: View → Themes.
- صيغة النسب: اختر المقياس → Format → Percentage، منزلتين عشريتين.
- احفظ الملف في `powerbi/saudi_stocks_dashboard.pbix`.
- خذ صور للصفحات واحفظها في `powerbi/screenshots/` بأسماء `overview.png` و `stock_detail.png` و `sectors.png` (الـ README يعرضها تلقائياً).
