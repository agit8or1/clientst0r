import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { ApolloClient, InMemoryCache, ApolloProvider, createHttpLink } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';
import { Provider as PaperProvider, MD3DarkTheme } from 'react-native-paper';
import * as SecureStore from 'expo-secure-store';
import Constants from 'expo-constants';

import AppNavigator from './src/navigation/AppNavigator';
import AuthProvider from './src/contexts/AuthContext';

// Get API URL from config
const API_URL = Constants.expoConfig.extra.graphqlUrl || 'http://localhost:8000/api/v2/graphql/';

// Create HTTP Link
const httpLink = createHttpLink({
  uri: API_URL,
});

// Auth Link - Add token to headers
const authLink = setContext(async (_, { headers }) => {
  const token = await SecureStore.getItemAsync('authToken');
  return {
    headers: {
      ...headers,
      authorization: token ? `Token ${token}` : '',
    },
  };
});

// Create Apollo Client
const client = new ApolloClient({
  link: authLink.concat(httpLink),
  cache: new InMemoryCache(),
});

// Custom Dark Theme
const theme = {
  ...MD3DarkTheme,
  colors: {
    ...MD3DarkTheme.colors,
    primary: '#0d6efd',
    secondary: '#6c757d',
    background: '#0d1117',
    surface: '#161b22',
    error: '#dc3545',
    success: '#28a745',
  },
};

export default function App() {
  return (
    <ApolloProvider client={client}>
      <PaperProvider theme={theme}>
        <AuthProvider>
          <NavigationContainer theme={theme}>
            <AppNavigator />
          </NavigationContainer>
        </AuthProvider>
      </PaperProvider>
    </ApolloProvider>
  );
}
