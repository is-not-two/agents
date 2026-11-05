/* Browser-only animation budget. No model, network, or server resources involved. */
export const MOTION_CONFIG = Object.freeze({
  fps: 30,
  maxPixelRatio: 2,
  minViewportWidth: 760,
  ringSegments: 144,
  ringCount: 3,
  nodeRadius: 0.09,
  dustCount: 144,
  introMilliseconds: 900,
  enterMilliseconds: 500,
  actionMilliseconds: 420,
  searchHitLimit: 12,
  dragSensitivity: 0.004,
  seaBreeze: Object.freeze({
    enabled: false,
    base: '/static/shilie/assets/sea-breeze/girl-base.webp',
    hair: '/static/shilie/assets/sea-breeze/hair.webp',
    skirt: '/static/shilie/assets/sea-breeze/skirt.webp',
    glow: '/static/shilie/assets/sea-breeze/glow.webp',
    video: '',
  }),
});
