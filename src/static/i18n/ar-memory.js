/* Arabic for the answer memory's page (memory.html) (plan 038). Terms from docs/design/arabic-glossary.md.
   One JSON object per `I18n.add(...)`, read by tests/test_i18n_catalogs.py.

   "Forget", which takes an answer out of the memory for good, is not in the
   glossary: it reads "حذف من الذاكرة", a deletion, as it cannot be undone. The
   scan's one sentence a disagreement carries (src/memory.py) is here too, for
   I18n.server: this page is the only one that shows it. */

I18n.add({
  "What your team has said before, and which of it still stands": "ما قاله فريقك سابقاً، وما لا يزال قائماً منه",
  "Every answer here is one a person wrote — from questionnaires the team filled in, written here by hand, or edited and approved on an answer card. New answers only arrive deliberately, one at a time. A draft nobody changed never reaches this page, however confident it was: what the model produced is not evidence about us. These are the strongest thing the system has to work from, so they are worth keeping true: correct one that has aged, retire one that was replaced, and settle the pairs that disagree.": "كل إجابة هنا كتبها شخص — من استبيانات ملأها الفريق، أو كُتبت هنا يدوياً، أو عُدّلت واعتُمدت في بطاقة إجابة. لا تصل الإجابات الجديدة إلا عن قصد، واحدة تلو الأخرى. ولا تصل إلى هذه الصفحة أبداً مسودةٌ لم يغيّرها أحد، مهما بلغت درجة الثقة فيها: فما أنتجه النموذج ليس دليلاً على ما نفعله. هذه أقوى ما يعتمد عليه النظام، لذا تستحق أن تبقى صحيحة: صحّح ما تقادم منها، وأوقف استخدام ما استُبدل، وافصل في الأزواج المتعارضة.",

  "Shared, for every product": "مشتركة لجميع المنتجات",
  "Used for every questionnaire.": "تُستخدم لجميع الاستبيانات.",
  "Used only for {name}'s questionnaires, beside the shared one.": "تُستخدم لاستبيانات {name} فقط، إلى جانب المشتركة.",

  "Two answers that disagree": "إجابتان متعارضتان",
  "Both were given to a real assessor and nothing says which is current. Choose the one that is our position — the other is kept as history and stops being used — or say they are not the same question after all.": "قُدّمت كلتاهما إلى مقيّم فعلي، ولا شيء يبيّن أيهما المعمول بها حالياً. اختر الإجابة التي تمثّل موقفنا — فتُحفظ الأخرى سجلاً ويتوقف استخدامها — أو بيّن أنهما ليستا عن السؤال نفسه.",
  "These two answers disagree.": "هاتان الإجابتان متعارضتان.",
  "the two answers disagree and nothing says which is current": "الإجابتان متعارضتان، ولا شيء يبيّن أيهما المعمول بها حالياً",
  "This one is our position": "هذه الإجابة تمثّل موقفنا",
  "They are not the same question": "ليستا عن السؤال نفسه",
  "no date recorded": "لا يوجد تاريخ مسجّل",

  "Add an answer": "إضافة إجابة",
  "For something we say that no questionnaire in the corpus happens to ask. It is retrieved exactly like the rest.": "لما نقوله في أمر لم يصادف أن سأل عنه أي استبيان في المجموعة. وتُسترجع تماماً كغيرها.",
  "The question, as an assessor would ask it": "السؤال، كما يطرحه المقيّم",
  "What we say": "ما نقوله",
  "Remember this": "احفظها في الذاكرة",
  "An entry needs both the question and the answer.": "تحتاج الإجابة المحفوظة إلى السؤال والإجابة معاً.",
  "Remembered. It is the first answer in the list below.": "حُفظت. إنها أول إجابة في القائمة أدناه.",
  "Remembered.": "حُفظت.",

  "Everything we have said": "كل ما قلناه",
  "Newest first. Search matches the question and the answer.": "الأحدث أولاً. يطابق البحث السؤال والإجابة.",
  "Search remembered answers…": "ابحث في الإجابات المحفوظة…",
  "Everything": "الكل",
  "In use": "قيد الاستخدام",
  "Replaced": "مستبدلة",
  "Any source": "أي مصدر",
  "From a questionnaire": "من استبيان",
  "Approved here": "اعتُمدت هنا",
  "Added by hand": "أُضيفت يدوياً",
  "Compare anything new against what we already remember": "قارن كل جديد بما نحفظه بالفعل",
  "Check for conflicts": "التحقق من التعارضات",
  "Show more": "عرض المزيد",
  "Loading…": "جارٍ التحميل…",
  "Nothing remembered yet. Add an answer above, or edit and approve an answer on a card.": "لا توجد إجابات محفوظة بعد. أضف إجابة في الأعلى، أو عدّل إجابة واعتمدها في بطاقتها.",
  "Nothing matches that.": "لا يوجد ما يطابق ذلك.",
  "Showing {shown} of {total}": "عرض {shown} من {total}",

  "in use": "قيد الاستخدام",
  "replaced": "مستبدلة",
  "approved here": "اعتُمدت هنا",
  "disagreements": "حالات تعارض",
  "still to compare": "بانتظار المقارنة",
  "approved": "معتمدة",
  "added by hand": "أُضيفت يدوياً",
  "from a questionnaire": "من استبيان",
  "approved by {name}": "اعتمدها {name}",
  "added by {name}": "أضافها {name}",

  "Put back in use": "إعادتها إلى الاستخدام",
  "Edit": "تعديل",
  "Move this answer to another memory": "نقل هذه الإجابة إلى ذاكرة أخرى",
  "Move to…": "نقل إلى…",
  "Forget": "حذف من الذاكرة",
  "Remove this answer from the memory entirely": "إزالة هذه الإجابة من الذاكرة نهائياً",
  "Forget this answer?\n\nIt stops being retrieved and cannot be recovered from here.": "هل تريد حذف هذه الإجابة من الذاكرة؟\n\nسيتوقف استرجاعها، ولا يمكن استعادتها من هنا.",
  "Save": "حفظ",
  "Cancel": "إلغاء",

  "Comparing what is new against what we already remember…": "جارٍ مقارنة الجديد بما نحفظه بالفعل…",
  "{conflicts} disagreement(s) and {replaced} replaced answer(s) found.": "حالات التعارض التي وُجدت: {conflicts}، والإجابات المستبدلة: {replaced}.",
  "Nothing new found.": "لم يُعثر على جديد.",
  "{n} still to compare — press again.": {
    "one": "لا تزال إجابة واحدة بانتظار المقارنة — اضغط مجدداً.",
    "two": "لا تزال إجابتان بانتظار المقارنة — اضغط مجدداً.",
    "few": "لا تزال {n} إجابات بانتظار المقارنة — اضغط مجدداً.",
    "many": "لا تزال {n} إجابة بانتظار المقارنة — اضغط مجدداً.",
    "other": "لا تزال {n} إجابة بانتظار المقارنة — اضغط مجدداً."
  },

  "Your changes on this page are not saved yet. Switch the language anyway, and lose them?": "لم تُحفظ تغييراتك في هذه الصفحة بعد. هل تريد تبديل اللغة على أي حال وفقدانها؟",
  "Request failed ({status})": "تعذّر تنفيذ الطلب ({status})",
  "That did not work. Check the address and try again.": "لم ينجح ذلك. تحقّق من البريد الإلكتروني وحاول مجدداً.",
  "Could not reach the server.": "تعذّر الوصول إلى الخادم."
});
