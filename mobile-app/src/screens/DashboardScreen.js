import React from 'react';
import { View, StyleSheet, ScrollView, RefreshControl } from 'react-native';
import { Card, Title, Paragraph, Button, Avatar } from 'react-native-paper';
import { useQuery, gql } from '@apollo/client';
import { useAuth } from '../contexts/AuthContext';

const DASHBOARD_STATS_QUERY = gql`
  query DashboardStats {
    dashboardStats {
      totalOrganizations
      totalAssets
      totalPasswords
      totalDocuments
      totalDiagrams
      activeMonitors
    }
  }
`;

export default function DashboardScreen({ navigation }) {
  const { user } = useAuth();
  const { data, loading, refetch } = useQuery(DASHBOARD_STATS_QUERY);

  const stats = data?.dashboardStats || {};

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={loading} onRefresh={refetch} tintColor="#0d6efd" />
      }
    >
      <View style={styles.header}>
        <Title style={styles.title}>Welcome, {user?.first_name || user?.username}!</Title>
        <Paragraph style={styles.subtitle}>Client St0r Dashboard</Paragraph>
      </View>

      <View style={styles.statsGrid}>
        <Card style={styles.statCard} onPress={() => navigation.navigate('Assets')}>
          <Card.Content style={styles.statContent}>
            <Avatar.Icon size={48} icon="server" style={styles.statIcon} />
            <Title style={styles.statValue}>{stats.totalAssets || 0}</Title>
            <Paragraph style={styles.statLabel}>Assets</Paragraph>
          </Card.Content>
        </Card>

        <Card style={styles.statCard} onPress={() => navigation.navigate('Passwords')}>
          <Card.Content style={styles.statContent}>
            <Avatar.Icon size={48} icon="lock" style={styles.statIcon} />
            <Title style={styles.statValue}>{stats.totalPasswords || 0}</Title>
            <Paragraph style={styles.statLabel}>Passwords</Paragraph>
          </Card.Content>
        </Card>

        <Card style={styles.statCard} onPress={() => navigation.navigate('Documents')}>
          <Card.Content style={styles.statContent}>
            <Avatar.Icon size={48} icon="file-document" style={styles.statIcon} />
            <Title style={styles.statValue}>{stats.totalDocuments || 0}</Title>
            <Paragraph style={styles.statLabel}>Documents</Paragraph>
          </Card.Content>
        </Card>

        <Card style={styles.statCard}>
          <Card.Content style={styles.statContent}>
            <Avatar.Icon size={48} icon="monitor" style={styles.statIcon} />
            <Title style={styles.statValue}>{stats.activeMonitors || 0}</Title>
            <Paragraph style={styles.statLabel}>Monitors</Paragraph>
          </Card.Content>
        </Card>

        <Card style={styles.statCard}>
          <Card.Content style={styles.statContent}>
            <Avatar.Icon size={48} icon="office-building" style={styles.statIcon} />
            <Title style={styles.statValue}>{stats.totalOrganizations || 0}</Title>
            <Paragraph style={styles.statLabel}>Organizations</Paragraph>
          </Card.Content>
        </Card>

        <Card style={styles.statCard}>
          <Card.Content style={styles.statContent}>
            <Avatar.Icon size={48} icon="sitemap" style={styles.statIcon} />
            <Title style={styles.statValue}>{stats.totalDiagrams || 0}</Title>
            <Paragraph style={styles.statLabel}>Diagrams</Paragraph>
          </Card.Content>
        </Card>
      </View>

      <Card style={styles.actionCard}>
        <Card.Title title="Quick Actions" />
        <Card.Content>
          <Button
            mode="contained"
            icon="plus"
            onPress={() => {}}
            style={styles.actionButton}
          >
            Add Asset
          </Button>
          <Button
            mode="contained"
            icon="lock-plus"
            onPress={() => {}}
            style={styles.actionButton}
          >
            Add Password
          </Button>
          <Button
            mode="contained"
            icon="file-plus"
            onPress={() => {}}
            style={styles.actionButton}
          >
            Add Document
          </Button>
        </Card.Content>
      </Card>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0d1117',
  },
  header: {
    padding: 20,
    paddingTop: 40,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#c9d1d9',
  },
  subtitle: {
    fontSize: 14,
    color: '#8b949e',
    marginTop: 4,
  },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    padding: 10,
  },
  statCard: {
    width: '48%',
    margin: '1%',
    backgroundColor: '#161b22',
    marginBottom: 12,
  },
  statContent: {
    alignItems: 'center',
    paddingVertical: 16,
  },
  statIcon: {
    backgroundColor: '#0d6efd',
    marginBottom: 8,
  },
  statValue: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#c9d1d9',
    marginVertical: 4,
  },
  statLabel: {
    fontSize: 12,
    color: '#8b949e',
    textAlign: 'center',
  },
  actionCard: {
    margin: 12,
    backgroundColor: '#161b22',
  },
  actionButton: {
    marginVertical: 6,
  },
});
