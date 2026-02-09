import React, { useState } from 'react';
import { View, StyleSheet, FlatList, RefreshControl } from 'react-native';
import { Searchbar, List, Avatar, IconButton, Text, FAB } from 'react-native-paper';
import { useQuery, gql } from '@apollo/client';
import * as Clipboard from 'expo-clipboard';

const PASSWORDS_QUERY = gql`
  query Passwords($search: String) {
    passwords(search: $search) {
      id
      name
      username
      url
      organization {
        name
      }
    }
  }
`;

export default function PasswordsScreen() {
  const [searchQuery, setSearchQuery] = useState('');
  const { data, loading, refetch } = useQuery(PASSWORDS_QUERY, {
    variables: { search: searchQuery },
  });

  const passwords = data?.passwords || [];

  const copyToClipboard = async (text) => {
    await Clipboard.setStringAsync(text);
  };

  const renderPassword = ({ item }) => (
    <List.Item
      title={item.name}
      description={`${item.username || 'No username'} • ${item.organization?.name || ''}`}
      left={(props) => (
        <Avatar.Icon
          {...props}
          icon="lock"
          style={{ backgroundColor: '#0d6efd' }}
        />
      )}
      right={(props) => (
        <IconButton
          {...props}
          icon="content-copy"
          onPress={() => copyToClipboard(item.username || '')}
        />
      )}
      onPress={() => {}}
      style={styles.listItem}
    />
  );

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Searchbar
          placeholder="Search passwords..."
          onChangeText={setSearchQuery}
          value={searchQuery}
          style={styles.searchbar}
        />
      </View>

      {passwords.length === 0 && !loading ? (
        <View style={styles.emptyState}>
          <Avatar.Icon size={80} icon="lock" style={styles.emptyIcon} />
          <Text style={styles.emptyText}>No passwords found</Text>
        </View>
      ) : (
        <FlatList
          data={passwords}
          renderItem={renderPassword}
          keyExtractor={(item) => item.id.toString()}
          refreshControl={
            <RefreshControl refreshing={loading} onRefresh={refetch} tintColor="#0d6efd" />
          }
          contentContainerStyle={styles.list}
        />
      )}

      <FAB
        icon="plus"
        style={styles.fab}
        onPress={() => {}}
        label="Add Password"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0d1117',
  },
  header: {
    padding: 16,
    paddingTop: 50,
  },
  searchbar: {
    backgroundColor: '#161b22',
  },
  list: {
    paddingHorizontal: 8,
  },
  listItem: {
    backgroundColor: '#161b22',
    marginBottom: 8,
    borderRadius: 8,
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 40,
  },
  emptyIcon: {
    backgroundColor: '#30363d',
    marginBottom: 16,
  },
  emptyText: {
    color: '#8b949e',
    fontSize: 16,
  },
  fab: {
    position: 'absolute',
    margin: 16,
    right: 0,
    bottom: 0,
    backgroundColor: '#0d6efd',
  },
});
