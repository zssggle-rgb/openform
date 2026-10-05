// Reused from the approved 2026-10-04 page shell.
const paths = {
 T01:'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h4"/>',
 T05:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4m-4-9 3 2 5-5"/>',
 T08:'<path d="m2 8 10-5 10 5-10 5-10-5m4 3v6q6 5 12 0v-6"/>',
 T12:'<path d="M3 6h7l2 3h9v11H3zm9 6v6m-3-3 3 3 3-3"/>',
 C01:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m1-16a3 3 0 0 1 0 6m2 3q4 1 4 7"/>',
 C02:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12m6-12v12"/>',
 C03:'<rect x="4" y="3" width="16" height="18" rx="2"/><circle cx="12" cy="9" r="2"/><path d="M8 17q0-6 8 0"/>',
 T10:'<path d="M3 4h7q2 0 2 3v14q0-3-3-3H3V4m18 0h-7q-2 0-2 3v14q0-3 3-3h6V4"/>',
 C06:'<path d="M3 3v18h18M6 15l4-5 4 3 6-8"/>',
};
export const icon = id => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[id]||paths.T01}</svg>`;
