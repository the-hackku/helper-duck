CREATE TABLE mentors(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  tickets_claimed INTEGER NOT NULL,
  tickets_closed INTEGER NOT NULL
);

CREATE TABLE tickets(
  id INTEGER PRIMARY KEY,
  message TEXT NOT NULL,
  author_id INTEGER NOT NULL,
  author TEXT NOT NULL,
  author_location TEXT NOT NULL,
  claimed BOOL NOT NULL,
  closed BOOL NOT NULL,
  mentor_assigned_id INTEGER,
  mentor_assigned TEXT,
  help_thread_id INTEGER,
  FOREIGN KEY(mentor_assigned_id) REFERENCES mentors(mentor_id)
);

