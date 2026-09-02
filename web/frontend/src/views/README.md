# `src/views`

`App.js` lazy-loads `src/views/<Name>.js` through stable paths. Each file is a
thin facade that resolves the corresponding screen from the default UI
manifest.

Real screens live in `src/themes/default/routes/`. Keep layout, copy, and
styled-components there.

Adding a top-level screen requires:

1. A route component in `src/themes/default/routes/`.
2. An entry in the default manifest's `routes` map.
3. A matching facade in this directory.
4. A route in `App.js`.

See `src/themes/README.md` for the complete runtime structure.
