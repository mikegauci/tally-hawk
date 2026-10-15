// TallyHawk brand mark: a hawk's head in profile. Eye, brow and beak line are cut out
// (evenodd) so it renders in currentColor on any background.
export function HawkMark({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="2.5 3.5 30 30"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M5 29C5 18 8 8.5 16 6.6C20 5.7 24.5 6.6 27.2 9.6C29.6 12.2 30.4 16.4 28.4 20.6C27.9 18.6 26.6 17.4 24.6 17.2L22.6 17.2C21.6 21.2 19 24.6 15.6 27L13.5 25.8L12.6 28.6L10 27.2L9 29.6L7.2 27.8ZM20.9 13.9a1.7 1.7 0 1 0-3.4 0a1.7 1.7 0 1 0 3.4 0ZM25 10.2C20.8 9.2 16.4 9.9 12.4 12.6C16.4 11.5 20.6 11.3 24.6 11.7ZM23.6 13C24.4 14.3 24.4 15.8 23.5 17.2L22.8 17.2C23.5 15.8 23.5 14.3 22.9 13Z"
      />
    </svg>
  );
}
