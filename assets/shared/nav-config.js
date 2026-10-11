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
    key: 'masterdata',
    label: 'Мастер-данные',
    href: '/md',
    icon: '📚',
    children: [
      { key: 'md:models',         label: 'Модели',            href: '/md#/d/models' },
      { key: 'md:items',          label: 'Экземпляры',        href: '/md#/d/items' },
      { key: 'md:kits',           label: 'Комплекты',         href: '/md#/d/kits' },
      { key: 'md:clients',        label: 'Клиенты',           href: '/md#/d/clients' },
      { key: 'md:counterparties', label: 'Контрагенты',       href: '/md#/d/counterparties' },
      { key: 'md:accounts',       label: 'Счета',             href: '/md#/d/accounts' },
      { key: 'md:import',         label: 'Импорт',            href: '/md#/import' },
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
      { key: 'admin:dict-builder', label: 'Конструктор справочников', href: '/md#/builder' },
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
