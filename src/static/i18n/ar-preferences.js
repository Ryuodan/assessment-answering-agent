/* Arabic for the preferences page (preferences.html) (plan 038). Terms from docs/design/arabic-glossary.md.
   One JSON object per `I18n.add(...)`, read by tests/test_i18n_catalogs.py.

   "Verdict", the Yes, No or Partially an answer opens with, is not in the
   glossary: it reads "الحكم". The built-in skills' names and descriptions
   (src/preferences.py, BUILTIN_SKILLS) are the app's own words, read through
   I18n.server; their instructions are what the model is told, and stay as
   they are, as does the instruction the preferences compose. The examples
   name an Arabic customer, as the English names Tailspin. A bold label and
   the sentence after it are two entries, each whole. */

I18n.add({
  "Your preferences": "تفضيلاتك",
  "How you want your answers to read — nobody else sees these": "كيف تريد أن تُصاغ إجاباتك — لا يراها أحد غيرك",

  "Language of the pages": "لغة الصفحات",
  "Answers are not changed by it: they follow the question’s language.": "لا تتغير بها الإجابات: فهي تتبع لغة السؤال.",

  "Every answer you draft": "كل إجابة تصوغها",
  "Set once, applied as each answer is drafted": "تُضبط مرة واحدة، وتُطبَّق عند صياغة كل إجابة",
  "A few fixed choices: verdict first, what to call us, clause numbers, tone": "بضعة خيارات ثابتة: الحكم أولاً، وكيف نُسمّى، وأرقام البنود، والأسلوب",
  "Everything starts “as drafted”": "يبدأ كل شيء «كما صيغت»",
  "Skills": "المهارات",
  "Only the answers you pick": "الإجابات التي تختارها فقط",
  "For a particular job: an auditor, a customer, a senior reader": "لغرض محدد: مدقق، أو عميل، أو قارئ في منصب رفيع",
  "Picked from the Skills menu above the answers, or asked for in the assistant": "تُختار من قائمة المهارات فوق الإجابات، أو تُطلب من المساعد",
  "Built in, or your own": "مدمجة، أو من كتابتك",

  "Applied to every answer you draft, in the assistant and in the workbench, after it has been drafted from the policies and checked. They change how an answer reads — never what it says: the Yes or No stays, the citations stay, and nothing the sources do not support is added. Each reworded answer keeps its original draft, which you can put back from the answer card.": "تُطبَّق على كل إجابة تصوغها، في المساعد وفي مساحة العمل، بعد صياغتها من السياسات والتحقق منها. وهي تغيّر طريقة صياغة الإجابة — لا مضمونها أبداً: تبقى «نعم» أو «لا»، وتبقى الاستشهادات، ولا يُضاف شيء لا تدعمه المصادر. وتحتفظ كل إجابة أُعيدت صياغتها بمسودتها الأصلية، ويمكنك استعادتها من بطاقة الإجابة.",
  "Recommended setup:": "الإعداد المقترح:",
  "how your team’s own answers read — the verdict first, the company by name, and policy references left to the citations.": "كما تُصاغ إجابات فريقك نفسه — الحكم أولاً، واسم الشركة صراحةً، وترك الإشارات إلى السياسات للاستشهادات.",
  "Use it": "استخدمه",
  "Filled in. Save to use it, or try it on a sample first.": "تمت التعبئة. احفظ لاستخدامه، أو جرّبه على مثال أولاً.",

  "Start with the verdict": "البدء بالحكم",
  "Yes, No, Partially or Not applicable": "نعم، أو لا، أو جزئياً، أو لا ينطبق",
  "As drafted": "كما صيغت",
  "Always, when the question asks for one": "دائماً، حين يتطلب السؤال ذلك",
  "Call the organisation": "تسمية المنظمة",
  "Leave empty to keep the draft’s wording": "اتركه فارغاً للإبقاء على صياغة المسودة",
  "Policy names and clause numbers": "أسماء السياسات وأرقام البنود",
  "In the answer text itself": "في نص الإجابة نفسه",
  "Keep them": "الإبقاء عليها",
  "Leave them to the citations": "تركها للاستشهادات",
  "Tone": "الأسلوب",
  "Formal": "رسمي",
  "Plain and direct": "بسيط ومباشر",
  "Questionnaires you open start with": "الاستبيانات التي تفتحها تبدأ بـ",
  "Full answers": "إجابات كاملة",
  "Brief answers": "إجابات مختصرة",
  "Also, always": "وأيضاً، دائماً",
  "Optional — anything the choices above do not cover": "اختياري — أي شيء لا تغطيه الخيارات أعلاه",
  "e.g. Write “Not applicable”, never “N/A”.": "مثال: اكتب «لا ينطبق» كاملةً، ولا تختصرها أبداً.",

  "What your answers get reworded with": "ما تُعاد به صياغة إجاباتك",
  "Nothing — your answers stay exactly as drafted.": "لا شيء — تبقى إجاباتك كما صيغت تماماً.",
  "Save": "حفظ",
  "Try it on a sample": "جرّبها على مثال",
  "Not saved yet.": "لم تُحفظ بعد.",
  "Saving…": "جارٍ الحفظ…",
  "Saved. Answers you draft from now on are reworded with these.": "حُفظت. ستُعاد بها صياغة الإجابات التي تصوغها من الآن.",
  "Saved. Answers you draft stay exactly as drafted.": "حُفظت. تبقى الإجابات التي تصوغها كما صيغت تماماً.",

  "Illustrative — a yes/no question (English)": "مثال توضيحي — سؤال بنعم أو لا (بالإنجليزية)",
  "Illustrative — a process question (English)": "مثال توضيحي — سؤال عن إجراء (بالإنجليزية)",
  "Paste one of your own…": "الصق مثالاً من عندك…",
  "Trying your preferences on a sample. Nothing is saved.": "تجربة تفضيلاتك على مثال. لا يُحفظ شيء.",
  "Trying this skill on a sample. Nothing is saved.": "تجربة هذه المهارة على مثال. لا يُحفظ شيء.",
  "Trying “{name}” on a sample. Nothing is saved.": "تجربة «{name}» على مثال. لا يُحفظ شيء.",
  "Sample answer": "إجابة المثال",
  "The question": "السؤال",
  "An answer as the system drafted it": "إجابة كما صاغها النظام",
  "Reword it": "إعادة صياغتها",
  "Close": "إغلاق",
  "Reworded": "بعد إعادة الصياغة",
  "Nothing to try: every choice is still as drafted.": "لا شيء لتجربته: كل الخيارات لا تزال «كما صيغت».",
  "Paste a question and an answer to try it on.": "الصق سؤالاً وإجابة لتجربتها عليهما.",
  "Rewording…": "جارٍ إعادة الصياغة…",
  "The rewording did not come back, so the answer would have been left as drafted. Try again.": "لم تعد إعادة الصياغة، فكانت الإجابة ستبقى كما صيغت. حاول مجدداً.",
  "It came back unchanged: there was nothing to change in this one.": "عادت دون تغيير: لم يكن فيها ما يُغيَّر.",

  "A named rewording for a particular job, applied only to the answers you pick: choose one from the Skills menu above the answers on either page, or ask the assistant — “give me the executive summary of the privacy answers”. Answers somebody wrote by hand are left as they are.": "إعادة صياغة لها اسم، لغرض محدد، تُطبَّق فقط على الإجابات التي تختارها: اختر واحدة من قائمة المهارات فوق الإجابات في أي من الصفحتين، أو اطلبها من المساعد — «أعطني الملخص التنفيذي لإجابات الخصوصية». أما الإجابات التي كتبها شخص بنفسه فتبقى كما هي.",
  "Built in": "مدمجة",
  "Yours": "مهاراتك",
  "+ Write a new skill": "+ كتابة مهارة جديدة",
  "None yet. Make a copy of a built-in one to change it, or write your own below.": "لا شيء بعد. أنشئ نسخة من مهارة مدمجة لتعديلها، أو اكتب مهارتك أدناه.",
  "built in": "مدمجة",
  "What it tells the rewording": "ما توجّه به إعادة الصياغة",
  "Try it": "جرّبها",
  "Make a copy to change": "إنشاء نسخة لتعديلها",
  "Duplicate": "نسخ",
  "Edit": "تعديل",
  "Delete": "حذف",
  "Delete the skill “{name}”?\n\nAnswers already reworded with it keep their wording.": "هل تريد حذف المهارة «{name}»؟\n\nتحتفظ الإجابات التي أُعيدت صياغتها بها بصياغتها.",
  "Name": "الاسم",
  "e.g. Tailspin format": "مثال: صيغة عميل الأفق",
  "When to use it (optional)": "متى تُستخدم (اختياري)",
  "e.g. Tailspin's supplier questionnaires: short, verdict first": "مثال: استبيانات الموردين لدى عميل الأفق: مختصرة، والحكم أولاً",
  "How the answers should read": "كيف ينبغي أن تُصاغ الإجابات",
  "e.g. Open with Yes, No or Partially. Then at most one short sentence. No policy names or clause numbers.": "مثال: ابدأ بنعم أو لا أو جزئياً، ثم جملة قصيرة واحدة على الأكثر، دون أسماء سياسات أو أرقام بنود.",
  "Save changes": "حفظ التغييرات",
  "Save skill": "حفظ المهارة",
  "Cancel": "إلغاء",

  "Auditor detail": "تفاصيل للمدقق",
  "For an auditor checking evidence: every specific kept, each tied to its policy.": "لمدقق يتحقق من الأدلة: تُحفظ كل التفاصيل، ويُربط كلٌّ منها بسياسته.",
  "Plain language": "لغة بسيطة",
  "For a customer who is not a security specialist.": "لعميل ليس متخصصاً في الأمن.",
  "Executive summary": "ملخص تنفيذي",
  "Two sentences for a senior reader: the position, and why.": "جملتان لقارئ في منصب رفيع: الموقف، وسببه.",
  "Bullet points": "نقاط موجزة",
  "For process questions: the verdict, then one line per control.": "لأسئلة الإجراءات: الحكم، ثم سطر لكل ضابط.",

  "Your changes on this page are not saved yet. Switch the language anyway, and lose them?": "لم تُحفظ تغييراتك في هذه الصفحة بعد. هل تريد تبديل اللغة على أي حال وفقدانها؟",
  "Request failed ({status})": "تعذّر تنفيذ الطلب ({status})",
  "That did not work. Check the address and try again.": "لم ينجح ذلك. تحقّق من البريد الإلكتروني وحاول مجدداً.",
  "Could not reach the server.": "تعذّر الوصول إلى الخادم."
});

/* The limits the preferences and the skills are held to, as the server says
   them (src/preferences.py), for I18n.error on this page: whole sentences, by
   pattern, as several carry a number or a name. ar-server.js is loaded first,
   and its own Arabic for one of these, if it has it, is the one used. */
I18n.addPatterns([
  [/^A skill needs a name\.$/, "تحتاج المهارة إلى اسم."],
  [/^A skill needs an instruction: how should the answers change\?$/, "تحتاج المهارة إلى تعليمات: كيف ينبغي أن تتغير الإجابات؟"],
  [/^A skill's name can be at most (\d+) characters\.$/, "يمكن أن يتكون اسم المهارة من $1 من الأحرف على الأكثر."],
  [/^A skill's description can be at most (\d+) characters\.$/, "يمكن أن يتكون وصف المهارة من $1 من الأحرف على الأكثر."],
  [/^A skill's instruction can be at most (\d+) characters\.$/, "يمكن أن تتكون تعليمات المهارة من $1 من الأحرف على الأكثر."],
  [/^You can keep at most (\d+) skills\. Remove one you no longer use first\.$/, "يمكنك الاحتفاظ بـ $1 من المهارات على الأكثر. أزل أولاً مهارة لم تعد تستخدمها."],
  [/^There is already a built-in skill called (['"])(.*)\1\. Make a copy to change it\.$/, "توجد مهارة مدمجة باسم «$2». أنشئ نسخة منها لتعديلها."],
  [/^You already have a skill called (['"])(.*)\1\.$/, "لديك مهارة باسم «$2» بالفعل."],
  [/^Built-in skills cannot be changed\. Make a copy and edit that instead\.$/, "لا يمكن تغيير المهارات المدمجة. أنشئ نسخة منها وعدّلها بدلاً من ذلك."],
  [/^What to call us can be at most (\d+) characters\.$/, "يمكن أن تتكون تسمية المنظمة من $1 من الأحرف على الأكثر."],
  [/^Write what to call us without quotation marks\.$/, "اكتب تسمية المنظمة دون علامات تنصيص."],
  [/^The extra line can be at most (\d+) characters; this one is (\d+)\.$/, "يمكن أن يتكون السطر الإضافي من $1 من الأحرف على الأكثر، وفي هذا السطر $2."]
]);
