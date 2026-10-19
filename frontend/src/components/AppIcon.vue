<script setup>
defineProps({ name: { type: String, default: 'overview' }, size: { type: [Number, String], default: 20 } })
const paths = {
  brand: ['M4 5h16v14H4z', 'm8 9 3 3-3 3', 'M13 15h3'],
  home: ['m3 10 9-7 9 7', 'M5 9v11h5v-6h4v6h5V9'],
  overview: ['M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z'],
  chat: ['M4 4h16v12H9l-5 4z', 'M8 8h8M8 12h5'],
  checklist: ['m3 6 2 2 3-4M11 6h10', 'm3 13 2 2 3-4M11 13h10', 'M4 20h3M11 20h10'],
  tasks: ['M4 4h16v16H4z', 'M9 8v8M15 8v5'],
  calendar: ['M4 6h16v14H4z', 'M8 3v6M16 3v6M4 11h16M8 15h2M14 15h2'],
  stages: ['M12 3 9 5 5 5 5 9 3 12l2 3v4h4l3 2 3-2h4v-4l2-3-2-3V5h-4z', 'm8 12 3 3 5-6'],
  members: ['M16 21v-3a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v3', 'M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8', 'M18 3a4 4 0 0 1 0 8M22 21v-3a4 4 0 0 0-3-3.9'],
  book: ['M12 5C9 3 6 3 3 4v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1z', 'M12 5v15M6 8h3M15 8h3M6 12h3M15 12h3'],
  menu: ['M4 6h16M4 12h16M4 18h16'],
  close: ['m6 6 12 12M18 6 6 18'],
  refresh: ['M20 7v5h-5', 'M4 17v-5h5', 'M6 7a7 7 0 0 1 12-2l2 2M4 17l2 2a7 7 0 0 0 12-2'],
  logout: ['M9 4H4v16h5M9 12h12m-4-4 4 4-4 4'],
  plus: ['M12 5v14M5 12h14'],
  check: ['m5 12 4 4L19 6'],
  info: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'M12 11v6M12 7h.01'],
  alert: ['m12 3 10 18H2z', 'M12 9v5M12 17h.01'],
  clock: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18', 'M12 7v5l3 2'],
  file: ['M5 3h9l5 5v13H5z', 'M14 3v5h5M8 12h8M8 16h5'],
  download: ['M12 3v12m-4-4 4 4 4-4', 'M4 16v5h16v-5'],
  upload: ['M12 16V4m-4 4 4-4 4 4', 'M4 16v5h16v-5'],
  search: ['M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14', 'm15 15 6 6'],
  filter: ['M3 4h18l-7 8v7l-4 2v-9z'],
  'arrow-right': ['M4 12h16m-6-6 6 6-6 6'],
  'arrow-left': ['M20 12H4m6-6-6 6 6 6'],
  link: ['M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2', 'M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2'],
}
</script>
<template>
  <svg class="app-icon" :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path v-for="(path, index) in paths[name] || paths.overview" :key="index" :d="path" />
  </svg>
</template>
