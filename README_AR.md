# مواقيت مساجد شيفلد — نسخة GitHub Pages المجانية

**التكلفة الشهرية المستهدفة: £0.** هذا المشروع يُنشر كموقع ثابت عبر **GitHub Pages**، وتستخدم **GitHub Actions** برنامج Python لقراءة مواعيد المساجد وتجهيز ملف `data/mosques.json`، دون خادم يعمل طوال اليوم أو قاعدة بيانات مدفوعة.

**مهم:** الملفات جاهزة للنشر لكنها **لم تُنشر بعد على حساب GitHub**، ولم تختبر الاتصالات الحقيقية من GitHub Actions. أوقات الإقامة لا تُعرض إلا عند قراءة مصدر مؤرخ بتاريخ شيفلد اليوم واجتياز التحقق. يجب مراجعة شروط المواقع والحصول على إذن من المساجد عند الحاجة قبل الإعلان عن الموقع كمرجع عام.

## النشر لأول مرة — بالمجان

1. أنشئ حسابًا مجانيًا في [GitHub](https://github.com/signup) إن لم يكن لديك واحد.
2. من GitHub اختر **New repository** وأنشئ مستودعًا اسمه **`sheffield-masjid-times`**، واختَر **Public**، واتركه **فارغًا** دون README أو ترخيص تلقائي. **المستودع العام ضروري للاستفادة من GitHub Pages في خطة GitHub Free.**
3. فك ضغط هذا الملف ZIP على جهازك. افتح الطرفية Terminal في مجلد المشروع الذي يحتوي على `app.py` و`.github` (لا ترفع ملف ZIP نفسه).
4. شغّل الأوامر التالية، بعد استبدال `YOUR_USERNAME` باسم المستخدم الخاص بك:

   ```bash
   git init
   git add .
   git commit -m "First free mosque times portal"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/sheffield-masjid-times.git
   git push -u origin main
   ```

   إن طلب GitHub تسجيل الدخول، استخدم طرق المصادقة التي يدعمها حسابك (مثل تطبيق GitHub Desktop أو مدير اعتماد Git). لا تضع كلمة المرور أو رمز وصول سري داخل الملفات.

5. افتح مستودعك في GitHub ثم: **Settings → Pages → Build and deployment → Source → GitHub Actions**.
6. افتح تبويب **Actions**، واختر **Publish Sheffield mosque times (free)** ثم **Run workflow → Run workflow** إن لم يبدأ النشر تلقائيًا أو فشلت أول محاولة قبل تفعيل Pages.
7. عندما تظهر علامة نجاح خضراء، افتح **Settings → Pages → Visit site**. العنوان المتوقّع:

   `https://YOUR_USERNAME.github.io/sheffield-masjid-times/`

8. افتح أيضًا ملف البيانات المنشور:

   `https://YOUR_USERNAME.github.io/sheffield-masjid-times/data/mosques.json`

   راجع `date` و`generated_at` و`status` و`source_date` لكل مسجد؛ إن كانت المصادر غير متاحة فستظهر مساجد الدليل بدون توقيت، لا ببيانات مزيفة.

## كيف يعمل التحديث الآلي؟

- الملف `.github/workflows/deploy-pages.yml` يشغّل المهمة كل **3 ساعات تقريبًا بالتوقيت المحلي في بريطانيا**، وعند إضافة تغيير إلى فرع `main` أو تشغيلها يدويًا من Actions.
- المهمة تثبّت حزم Python، وتشغّل الاختبارات، ثم تجمع المصادر وتنشئ مجلد `public/` وترفع **الملفات الثابتة فقط** إلى GitHub Pages. لا تُحفظ بيانات سرية أو كلمات مرور أو ملفات النشر على خدمات مدفوعة.
- **الجدولة غير مضمونة بالدقيقة.** قد تتأخر بعض المهام أو تُتخطّى؛ إذا مرّت أكثر من **5 ساعات** على `generated_at` أو تغيّر اليوم في بريطانيا، تُخفي الصفحة المواعيد حتى لا تعرض نسخة قديمة على أنها مواعيد اليوم.
- قد تُعطَّل الجدولة في المستودعات العامة بعد **60 يومًا دون نشاط بالمستودع**. راجع تبويب Actions دوريًا، وأعد تفعيل `Publish Sheffield mosque times (free)` من القائمة إذا توقفت. تشغيل إجراء يدوي ينشر نسخة حالية، لكنه لا يضمن استمرار الجدولة.
- التحديث اليدوي من زر الصفحة **يعيد تحميل النسخة المنشورة فقط**؛ لتجميع بيانات جديدة فورًا استخدم **Actions → Publish Sheffield mosque times (free) → Run workflow**.

## المساجد الثمانية والمصادر

| المسجد | قراءة تلقائية؟ | طريقة التعامل مع البيانات |
| --- | --- | --- |
| [Al-Huda Islamic Centre](https://masjidhudasheff.com/) | نعم | يجب أن تتطابق بيانات الصفحة مع تاريخ شيفلد اليوم |
| [Masjid Sunnah](https://masjidsunnahsheffield.co.uk/) | قارئ جاهز، غير مؤرخ | تُحجب أوقات الصفحة عن المقارنة لأنها لا تحمل تاريخ سريان مؤكدًا |
| [Muslim Welfare House](https://www.mwhs.org.uk/) | نعم | الصفحة اليومية المؤرخة؛ إن قيل «العشاء بعد المغرب» دون ساعة تُعرض الصلوات الأربع الأخرى ولا نخمن الخامسة |
| [Industry Road Mosque](https://www.industryroadmosque.com/prayer-times/) | نعم | يجب وجود تاريخ اليوم وصحة ترتيب مواقيت البداية والإقامة؛ يُرفض الجدول عند وقت غير منطقي |
| [Masjid Umar (YMA)](https://www.ymasheffield.org/prayer-timetable) | ليس بعد | المصدر PDF، يظهر رابط التحميل الرسمي |
| [Madina Masjid](https://mawaqit.net/en/madina-masjid-sheffield-sheffield-s8-0zu-united-kingdom) | ليس بعد | رابط Mawaqit الذي وضعه المسجد على موقعه |
| [Sheffield Grand Mosque](https://emaantrust.mosqueprayertimes.org/prayer-times) | ليس بعد | صفحة المواقيت الرسمية؛ القارئ لم يجهز |
| [Baitul Mukarram](https://www.baitulmukarramjamemasjid.com/) | ليس بعد | رابط موقع المسجد، دون تخمين أوقات |

**هذه أربعة برامج قراءة، وليست أربعة مصادر مؤكدة اليوم.** ترتبط دقة العرض بسلامة موقع المسجد في وقت التشغيل وصحة البيانات المنشورة فيه. النسخة الحالية ليست معتمدة من إدارة أي مسجد، ولا تشمل أوقات صلاة الجمعة أو مناسبات رمضان الخاصة.

## تشغيل نسخة آمنة على جهازك (اختياري)

يتطلب **Python 3.11+**. للتجربة دون الاتصال بمواقع المساجد:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/build_static.py --offline --output public
python -m http.server 8000 --directory public
```

افتح `http://localhost:8000`. تعرض النسخة المحلية دليل المساجد لكن **بلا مواقيت** لأن خيار `--offline` يمنع الجلب. للتجميع الفعلي من المواقع الرسمية، استبدل أمر البناء بـ:

```bash
python scripts/build_static.py --output public
```

ثم أعد تحميل الصفحة. إذا فشل اتصالك بالمواقع، ستظهر رسائل التحقق وروابط المصادر بدل بيانات غير مؤكدة.

## الجودة والسلامة والقيود

- التوقيت المستخدم: `Europe/London` (GMT/BST حسب التاريخ).
- يَمنع القارئ تحويلات URL المفاجئة، ويتحقق من نوع ملف HTML وطول الاستجابة، ولا يسمح بإدخال روابط عشوائية من الزوّار.
- تقبل الواجهة أوقات الإقامة المؤرخة لهذا اليوم فقط؛ أرقام مصادر غير مؤرخة لا تظهر في المقارنة ولا في حساب أقرب إقامة.
- لا توجد لوحة تحكم لتحرير أوقات المساجد، ولا حسابات مستخدمين ولا جمع بيانات مواقع الزوار. تستضيف GitHub Pages الصفحة وقد تسجل عناوين IP لأغراض أمنية وفق سياسة GitHub.
- استخدام بيانات مواقع المساجد قد يتطلب موافقتها أو اتباع شروطها و`robots.txt`. يُفضّل الاتفاق على مصدر آمن مرخّص أو جدول مشترك لكل مسجد قبل إطلاق موقع يعتمد عليه المصلون.
- **حدود المجانية:** الموقع عام، وGitHub يضع قيودًا على الاستخدام ويجوز أن تتغير خططه. تجنّب شراء عنوان نطاق، أو تشغيل أدوات كبيرة مدفوعة، أو تفعيل حوسبة إضافية مدفوعة.

## وثائق GitHub الرسمية

- الاستضافة المجانية: https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- إعداد مصدر النشر: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- GitHub Actions المجانية للمستودعات العامة: https://docs.github.com/en/actions/concepts/billing-and-usage
- الجدولة والإيقاف عند عدم النشاط: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

**بعد النشر:** تحقق يدويًا من المصدر الرسمي لكل مسجد قبل دعوة المصلين للاعتماد على الموقع، خصوصًا عند تغيير الساعة أو في رمضان.
