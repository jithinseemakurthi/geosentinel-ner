import { describe, expect, it } from 'vitest';
import { DEFAULT_CENTER, DISTRICT_COORDS, districtCenter } from './districts';

describe('DISTRICT_COORDS', () => {
  it('covers all eight NER states with at least one district', () => {
    const states = new Set([
      'Itanagar', // Arunachal Pradesh
      'Dispur', // Assam
      'Imphal', // Manipur
      'Shillong', // Meghalaya
      'Aizawl', // Mizoram
      'Kohima', // Nagaland
      'Gangtok', // Sikkim
      'Agartala', // Tripura
    ]);
    for (const district of states) {
      expect(DISTRICT_COORDS[district], `missing ${district}`).toBeDefined();
    }
  });

  it('has valid WGS84 coordinates inside the NER bounding box', () => {
    for (const [district, point] of Object.entries(DISTRICT_COORDS)) {
      expect(point.lat, district).toBeGreaterThan(20);
      expect(point.lat, district).toBeLessThan(30);
      expect(point.lng, district).toBeGreaterThan(85);
      expect(point.lng, district).toBeLessThan(98);
    }
  });
});

describe('districtCenter', () => {
  it('returns coordinates for a known district', () => {
    expect(districtCenter('Aizawl')).toEqual({ lng: 92.7176, lat: 23.7271 });
  });

  it('falls back to the regional centroid for unknown input', () => {
    expect(districtCenter('Atlantis')).toEqual(DEFAULT_CENTER);
    expect(districtCenter(null)).toEqual(DEFAULT_CENTER);
    expect(districtCenter(undefined)).toEqual(DEFAULT_CENTER);
  });

  it('DEFAULT_CENTER itself is valid', () => {
    expect(DEFAULT_CENTER.lat).toBeGreaterThan(20);
    expect(DEFAULT_CENTER.lng).toBeGreaterThan(85);
  });
});
