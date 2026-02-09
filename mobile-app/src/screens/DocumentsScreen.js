import React, { useState } from 'react';
import { View, StyleSheet, FlatList, RefreshControl } from 'react-native';
import { Searchbar, List, Avatar, Chip, Text, FAB } from 'react-native-paper';
import { useQuery, gql } from '@apollo/client';

const DOCUMENTS_QUERY = gql`
  query Documents($search: String) {
    documents(search: $search) {
      id
      title
      content
      category
      createdAt
      updatedAt
      organization {
        name
      }
    }
  }
`;

export default function DocumentsScreen() {
  const [searchQuery, setSearchQuery] = useState('');
  const { data, loading, refetch } = useQuery(DOCUMENTS_QUERY, {
    variables: { search: searchQuery },
  });

  const documents = data?.documents || [];

  const getCategoryColor = (category) => {
    const colors = {
      procedure: '#0d6efd',
      policy: '#6c757d',
      guide: '#28a745',
      troubleshooting: '#ffc107',
      other: '#6c757d',
    };
    return colors[category?.toLowerCase()] || '#6c757d';
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString();
  };

  const renderDocument = ({ item }) => (
    <List.Item
      title={item.title}
      description={`${item.organization?.name || ''} • Updated ${formatDate(item.updatedAt)}`}
      left={(props) => (
        <Avatar.Icon
          {...props}
          icon="file-document"
          style={{ backgroundColor: getCategoryColor(item.category) }}
        />
      )}
      right={() => (
        <Chip
          mode="outlined"
          style={{ borderColor: getCategoryColor(item.category) }}
          textStyle={{ fontSize: 11 }}
        >
          {item.category || 'Other'}
        </Chip>
      )}
      onPress={() => {}}
      style={styles.listItem}
    />
  );

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Searchbar
          placeholder="Search documents..."
          onChangeText={setSearchQuery}
          value={searchQuery}
          style={styles.searchbar}
        />
      </View>

      {documents.length === 0 && !loading ? (
        <View style={styles.emptyState}>
          <Avatar.Icon size={80} icon="file-document" style={styles.emptyIcon} />
          <Text style={styles.emptyText}>No documents found</Text>
        </View>
      ) : (
        <FlatList
          data={documents}
          renderItem={renderDocument}
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
        label="Add Document"
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
