# RoutePulse

RoutePulse is a simulated earthquake-response route exercise. It does not use live incident data and must not be used for real-world rescue navigation.

## Frontend

Requires Node.js 18 or later.

```bash
npm install
npm run dev
```

Open the address printed by Vite. Run `npm run build` for a production build and `npm run preview` to preview it.

The React and TypeScript frontend includes an overview and a rescue-route workspace. The overview map displays the supplied historical 2024 Noto earthquake and road recovery data; it is not live and requires a network connection for map tiles and some icons. The rescue map renders roads, buildings and selected other features from the bundled `src/map.osm` extract alongside the supplied Anamizu boundary; it does not use online map tiles. The extract only covers its specified area and is neither live nor a representation of 2024 road conditions. The bundled map data, historical images and GeoJSON are included in the build output.

Route calculations, reports, exercise updates, and supported questions use the isolated in-memory mock service in `src/mockApi.ts`; there is no backend. The mock routes and reports are not geographically linked to either map. Mock state resets on a page reload. Replace the service with the agreed API when integrating the backend. Neither map nor the simulated routes should be used for real-world rescue navigation.

Try calculating S → T, reporting `road-sa` blocked, advancing the simulated external update, and then reporting `road-bt` suspected to explore route changes, conflict, and no-path states. Observation times are simulated UTC scenario times.
