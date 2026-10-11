/**
 * Secure token storage.
 *
 * The refresh token is long-lived, so it lives in `expo-secure-store` (Keychain on
 * iOS, EncryptedSharedPreferences on Android). The access token is short-lived and
 * deliberately kept in memory only: persisting it would widen the blast radius of a
 * device compromise for very little benefit.
 */

import * as SecureStore from 'expo-secure-store';

const REFRESH_TOKEN_KEY = 'carwash.refresh_token';

const isSecureStoreAvailable = async (): Promise<boolean> => {
  try {
    return await SecureStore.isAvailableAsync();
  } catch {
    return false;
  }
};

export const tokenStorage = {
  /**
   * Read the refresh token.
   *
   * Falls back to unencrypted storage only if the Keychain is unavailable, so a
   * developer on an unsupported simulator is not locked out. The failure is logged
   * because it is a real security downgrade in production.
   */
  async getRefreshToken(): Promise<string | null> {
    if (await isSecureStoreAvailable()) {
      try {
        return await SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
      } catch (error) {
        console.warn('[auth] secure read failed', error);
        return null;
      }
    }

    console.warn('[auth] SecureStore unavailable; refresh token is not persisted securely.');
    return null;
  },

  async setRefreshToken(token: string): Promise<void> {
    if (await isSecureStoreAvailable()) {
      await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token, {
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      });
    }
  },

  async clearRefreshToken(): Promise<void> {
    if (await isSecureStoreAvailable()) {
      try {
        await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
      } catch (error) {
        console.warn('[auth] secure delete failed', error);
      }
    }
  },
};
