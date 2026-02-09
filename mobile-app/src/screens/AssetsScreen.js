import React, { useState } from 'react';
import { View, StyleSheet, FlatList, RefreshControl } from 'react-native';
import { Searchbar, List, Avatar, Chip, Text, FAB } from 'react-native-paper';
import { useQuery, gql } from '@apollo/client';

const ASSETS_QUERY = gql`
  query Assets($search: String) {
    assets(search: $search) {
      id
      name
      assetType
      manufacturer
      model
      status
      organization {
        name
      }
    }
  }
`;

export default function AssetsScreen({ navigation }) {
  const [searchQuery, setSearchQuery] = useState('');
  const { data, loading, refetch } = useQuery(ASSETS_QUERY, {
    variables: { search: searchQuery },
  });

  const assets = data?.assets || [];

  const getStatusColor = (status) => {
    const colors = {
      active: '#28a745',
      inactive: '#6c757d',
      retired: '#dc3545',
      maintenance: '#ffc107',
    };
    return colors[status?.toLowerCase()] || '#6c757d';
  };

  const getAssetIcon = (assetType) => {
    const icons = {
      server: 'server',
      desktop: 'desktop-tower',
      laptop: 'laptop',
      printer: 'printer',
      network: 'lan',
      phone: 'phone',
      tablet: 'tablet',
      other: 'devices',
    };
    return icons[assetType?.toLowerCase()] || 'devices';
  };

  const renderAsset = ({ item }) => (
    <List.Item
      title={item.name}
      description={`${item.manufacturer || ''} ${item.model || ''}`.trim()}
      left={(props) => (
        <Avatar.Icon
          {...props}
          icon={getAssetIcon(item.assetType)}
          style={{ backgroundColor: '#0d6efd' }}
        />
      )}
      right={() => (
        <Chip
          mode="flat"
          style={{ backgroundColor: getStatusColor(item.status) }}
          textStyle={{ color: '#fff', fontSize: 11 }}
        >
          {item.status || 'Unknown'}
        </Chip>
      )}
      onPress={() => navigation.navigate('AssetDetail', { assetId: item.id })}
      style={styles.listItem}
    />
  );

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Searchbar
          placeholder="Search assets..."
          onChangeText={setSearchQuery}
          value={searchQuery}
          style={styles.searchbar}
        />
      </View>

      {assets.length === 0 && !loading ? (
        <View style={styles.emptyState}>
          <Avatar.Icon size={80} icon="server" style={styles.emptyIcon} />
          <Text style={styles.emptyText}>No assets found</Text>
        </View>
      ) : (
        <FlatList
          data={assets}
          renderItem={renderAsset}
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
        label="Add Asset"
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
