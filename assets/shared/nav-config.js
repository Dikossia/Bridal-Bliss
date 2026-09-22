// ============================================================
// nav-config.js — ДЕРЕВО НАВИГАЦИИ приложения «Учёт».
// ЕДИНСТВЕННЫЙ источник правды о составе и структуре разделов.
// Чтобы добавить раздел (например, «Администрирование») — допишите узел сюда,
// больше нигде ничего менять не нужно (это статика, отдаётся Nginx).
//
// Узел:
//   key      — уникальный идентификатор (по нему подсвечивается активный пункт)
//   label    — подпись
//   icon     — эмодзи-иконка (без внешних зависимостей)
//   href     — ссылка (для «листьев»; у групп можно не указывать)
//   children — массив вложенных пунктов (делает узел раскрываемой группой)
//
// Ключи дочерних справочников вида 'dict:<key>' соответствуют маршрутам
// /dict/<key> модуля «Справочники».
// ============================================================

export const NAV = [
  {
    key: 'dictionaries',
    label: 'Справочники',
    href: '/dictionaries',
    icon: '📚',
    children: [
      { key: 'dict:income_items',   label: 'Статьи доходов',    href: '/dict/income_items' },
      { key: 'dict:expense_items',  label: 'Категории расходов', href: '/dict/expense_items' },
      { key: 'dict:expense_types',  label: 'Виды расходов',      href: '/dict/expense_types' },
      { key: 'dict:companies',      label: 'Компании',           href: '/dict/companies' },
      { key: 'dict:counterparties', label: 'Контрагенты',        href: '/dict/counterparties' },
      { key: 'dict:objects',        label: 'Объекты',            href: '/dict/objects' },
      { key: 'dict:contracts',      label: 'Договоры',           href: '/dict/contracts' },
    ],
  },
  {
    key: 'operations',
    label: 'Операции',
    icon: '🧾',
    href: '/operations',
  },
  {
    key: 'report',
    label: 'Отчёты',
    icon: '📊',
    href: '/report',
  },
  {
    key: 'admin',
    label: 'Администрирование',
    href: '/admin',
    icon: '⚙️',
    children: [
      { key: 'admin:roles',        label: 'Роли и полномочия',        href: '/admin/roles' },
      { key: 'admin:dict-builder', label: 'Построитель справочников',  href: '/admin/dict-builder' },
      { key: 'admin:forms',        label: 'Редактор форм ввода',       href: '/admin/forms' },
    ],
  },

  // --- Пример будущего раздела (раскомментируйте и дополните при необходимости) ---
  // {
  //   key: 'settings',
  //   label: 'Настройки',
  //   icon: '🔧',
  //   children: [
  //     { key: 'settings:profile', label: 'Профиль', href: '/settings/profile' },
  //   ],
  // },
];

// Куда ведёт логотип «Учёт» в шапке сайдбара.
export const HOME_HREF = '/home';
