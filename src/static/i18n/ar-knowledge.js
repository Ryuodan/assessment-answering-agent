/* Arabic for the knowledge base's page (knowledge.html) (plan 038). Terms from docs/design/arabic-glossary.md.
   One JSON object per `I18n.add(...)`, read by tests/test_i18n_catalogs.py.

   "Guideline", the kind of document a policy or standard is here, is not in the
   glossary: it reads "وثيقة إرشادية" throughout. What cards.js draws on this
   page (the authority badge, the questions asked before removing) is in
   ar-cards.js. A bold label and the sentence after it are two entries, each
   whole, and so is the lede's sentence and the link that ends it: the test
   reads a `data-i18n-html` entry's tags as English words. */

I18n.add({
  "The policies and standards every answer is drawn from": "السياسات والمعايير التي تُستمد منها كل إجابة",
  "Everything the agent answers from: your policies here, and the answers the team has already given in the": "كل ما يجيب منه الوكيل: سياساتك هنا، والإجابات التي سبق أن قدّمها الفريق في",
  "answer memory": "ذاكرة الإجابات",

  "Choose a knowledge base…": "اختر قاعدة المعرفة…",
  "Shared, for every product": "مشتركة لجميع المنتجات",
  "Choose which knowledge base to work on: the shared one, used for every product, or one product’s own.": "اختر قاعدة المعرفة التي تعمل عليها: المشتركة المستخدمة لجميع المنتجات، أو القاعدة الخاصة بأحد المنتجات.",
  "Choose which knowledge base to work on: the shared one, used for every product, or one product's own.": "اختر قاعدة المعرفة التي تعمل عليها: المشتركة المستخدمة لجميع المنتجات، أو القاعدة الخاصة بأحد المنتجات.",
  "Used only for {name}'s questionnaires, beside the shared one.": "تُستخدم لاستبيانات {name} فقط، إلى جانب المشتركة.",
  "Used for every questionnaire.": "تُستخدم لجميع الاستبيانات.",

  "Guidelines": "الوثائق الإرشادية",
  "Policies, standards and reference material the answers are drawn from.": "السياسات والمعايير والمواد المرجعية التي تُستمد منها الإجابات.",
  "Drop PDF or DOCX files here, or click to choose": "أفلت ملفات PDF أو DOCX هنا، أو انقر للاختيار",
  "Whose document is this?": "لمن هذه الوثيقة؟",
  "Ours.": "وثيقتنا.",
  "Something we wrote and are bound by — it says what we do.": "كتبناها ونلتزم بها — تبيّن ما نفعله.",
  "A requirement we are subject to.": "متطلب نخضع له.",
  "A law, regulation or someone else’s framework — PDPL, NCA ECC, SDAIA. It says what we must do, which is not evidence that we do it.": "قانون أو لائحة أو إطار وضعته جهة أخرى — PDPL، NCA ECC، SDAIA. يبيّن ما يجب علينا فعله، وهذا ليس دليلاً على أننا نفعله.",
  "Index guidelines": "فهرسة الوثائق الإرشادية",
  "Choose the knowledge base they go to, above, first.": "اختر أولاً، في الأعلى، قاعدة المعرفة التي ستُضاف إليها.",
  "Indexing {n} guideline(s). Large documents take a minute each.": {
    "one": "جارٍ فهرسة وثيقة إرشادية واحدة. تستغرق الوثيقة الكبيرة دقيقة تقريباً.",
    "two": "جارٍ فهرسة وثيقتين إرشاديتين. تستغرق كل وثيقة كبيرة دقيقة تقريباً.",
    "few": "جارٍ فهرسة {n} وثائق إرشادية. تستغرق كل وثيقة كبيرة دقيقة تقريباً.",
    "many": "جارٍ فهرسة {n} وثيقة إرشادية. تستغرق كل وثيقة كبيرة دقيقة تقريباً.",
    "other": "جارٍ فهرسة {n} وثيقة إرشادية. تستغرق كل وثيقة كبيرة دقيقة تقريباً."
  },
  "Indexed {indexed}/{n} file(s) — {chunks} chunks.": "تمت فهرسة {indexed} من أصل {n} من الملفات — عدد المقاطع: {chunks}.",
  "Indexed {indexed}/{n} file(s) — {chunks} chunks, {pairs} Q/A pairs.": "تمت فهرسة {indexed} من أصل {n} من الملفات — عدد المقاطع: {chunks}، وعدد أزواج الأسئلة والإجابات: {pairs}.",
  "– {name}: skipped, identical to {other}": "– {name}: تم تخطيه، فهو مطابق لـ {other}",

  "The team’s own answers": "إجابات الفريق نفسه",
  "Kept in the answer memory, not here, and added one at a time: written on that page, or edited and approved on an answer card.": "تُحفظ في ذاكرة الإجابات لا هنا، وتُضاف واحدة تلو الأخرى: تُكتب في تلك الصفحة، أو تُعدَّل وتُعتمد في بطاقة إجابة.",
  "Open the answer memory →": "افتح ذاكرة الإجابات ←",

  "What is indexed": "الوثائق في قاعدة المعرفة",
  "Loading…": "جارٍ التحميل…",
  "Refresh": "تحديث",
  "The answer memory is not affected": "لا تتأثر ذاكرة الإجابات",
  "Remove every policy document": "إزالة جميع وثائق السياسات",
  "Choose a knowledge base above to see what is indexed in it.": "اختر قاعدة معرفة في الأعلى لترى الوثائق التي فيها.",
  "Nothing indexed yet. Upload your policies above.": "لا توجد وثائق مفهرسة بعد. ارفع سياساتك في الأعلى.",
  "Could not load the knowledge base: {error}": "تعذّر تحميل قاعدة المعرفة: {error}",
  "{n} file(s)": {
    "one": "ملف واحد",
    "two": "ملفان",
    "few": "{n} ملفات",
    "many": "{n} ملفاً",
    "other": "{n} ملف"
  },
  "{count} guideline chunks": {
    "one": "مقطع إرشادي واحد",
    "two": "مقطعان إرشاديان",
    "few": "{count} مقاطع إرشادية",
    "many": "{count} مقطعاً إرشادياً",
    "other": "{count} مقطع إرشادي"
  },
  "{count} previous answers": {
    "one": "إجابة سابقة واحدة",
    "two": "إجابتان سابقتان",
    "few": "{count} إجابات سابقة",
    "many": "{count} إجابة سابقة",
    "other": "{count} إجابة سابقة"
  },
  "Manage the answer memory": "إدارة ذاكرة الإجابات",
  "answers": "إجابات",
  "guideline": "وثيقة إرشادية",
  "view": "عرض",
  "remove": "إزالة",
  "Open the document, and the text the agent read out of it": "افتح الوثيقة، والنص الذي قرأه الوكيل منها",
  "Uploaded completed assessment": "استبيان مكتمل مرفوع",
  "Uploaded guideline": "وثيقة إرشادية مرفوعة",
  "Removed {name}.": "تمت إزالة {name}.",
  "Removed every policy document from the shared knowledge base.": "تمت إزالة جميع وثائق السياسات من قاعدة المعرفة المشتركة.",
  "Removed every policy document from {name}'s knowledge base.": "تمت إزالة جميع وثائق السياسات من قاعدة معرفة {name}.",
  "{n} file(s) could not be removed from the server ({names}); see the log.": {
    "one": "تعذّرت إزالة ملف واحد من الخادم ({names})؛ راجع السجل.",
    "two": "تعذّرت إزالة ملفين من الخادم ({names})؛ راجع السجل.",
    "few": "تعذّرت إزالة {n} ملفات من الخادم ({names})؛ راجع السجل.",
    "many": "تعذّرت إزالة {n} ملفاً من الخادم ({names})؛ راجع السجل.",
    "other": "تعذّرت إزالة {n} ملف من الخادم ({names})؛ راجع السجل."
  },

  "Download original": "تنزيل الملف الأصلي",
  "Close": "إغلاق",
  "Document preview": "معاينة الوثيقة",
  "Extracted text": "النص المستخرج",
  "Extracting text… the first view may take a minute.": "جارٍ استخراج النص… قد يستغرق العرض الأول دقيقة.",
  "{count} extracted characters.": {
    "one": "حرف واحد مستخرج.",
    "two": "حرفان مستخرجان.",
    "few": "{count} أحرف مستخرجة.",
    "many": "{count} حرفاً مستخرجاً.",
    "other": "{count} حرف مستخرج."
  },

  "Request failed ({status})": "تعذّر تنفيذ الطلب ({status})",
  "That did not work. Check the address and try again.": "لم ينجح ذلك. تحقّق من البريد الإلكتروني وحاول مجدداً.",
  "Could not reach the server.": "تعذّر الوصول إلى الخادم."
});
