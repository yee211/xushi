import { registerPlugin } from '@capacitor/core';

// Credentials stay in Android's Keystore-encrypted, backup-excluded storage.
export const savedAccountsApi = registerPlugin('SavedAccounts');
