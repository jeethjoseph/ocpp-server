import { Preferences } from '@capacitor/preferences';

export interface RecentCharger {
  charge_point_string_id: string;
  charger_name: string;
  station_name: string;
  last_used: string;
}

const STORAGE_KEY = 'recent_chargers';
const MAX_RECENT_CHARGERS = 10;

export const recentChargersStorage = {
  async getAll(): Promise<RecentCharger[]> {
    try {
      const { value } = await Preferences.get({ key: STORAGE_KEY });
      if (!value) return [];
      const parsed = JSON.parse(value) as RecentCharger[];
      return parsed.sort(
        (a, b) => new Date(b.last_used).getTime() - new Date(a.last_used).getTime()
      );
    } catch (e) {
      console.error('Failed to read recent chargers:', e);
      return [];
    }
  },

  async add(charger: Omit<RecentCharger, 'last_used'>): Promise<void> {
    try {
      const existing = await this.getAll();
      const filtered = existing.filter(
        (c) => c.charge_point_string_id !== charger.charge_point_string_id
      );
      const updated: RecentCharger[] = [
        { ...charger, last_used: new Date().toISOString() },
        ...filtered,
      ].slice(0, MAX_RECENT_CHARGERS);
      await Preferences.set({ key: STORAGE_KEY, value: JSON.stringify(updated) });
    } catch (e) {
      console.error('Failed to save recent charger:', e);
    }
  },

  async clear(): Promise<void> {
    try {
      await Preferences.remove({ key: STORAGE_KEY });
    } catch (e) {
      console.error('Failed to clear recent chargers:', e);
    }
  },
};
